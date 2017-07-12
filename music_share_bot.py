import os
import time
import datetime
import requests
import webbrowser

import spotipy

from slackclient import SlackClient
from googleapiclient import discovery
from oauth2client import client, file


# Slack @music_share bot constants
BOT_ID = os.environ.get("BOT_ID")
AT_BOT = "<@" + BOT_ID + ">"
# TODO: Handle 'rate' commands (currently 'share' only). Read from the spreadsheet by URL?
EXAMPLE_COMMANDS = ["share", "rate"]

# Spotify Creds
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")

# Google Creds
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
API_KEY = os.environ.get("API_KEY")

# Instantiate Slack client
sc = SlackClient(os.environ.get('SLACK_BOT_TOKEN'))


def parse_rtm_output(slack_rtm_output):
    """
    The Slack Real Time Messaging API is an events firehose. This parsing function returns None unless a message is
    directed at the Bot, in which case the RTM output is returned (a list).
    """
    output_list = slack_rtm_output

    if output_list and len(output_list) > 0:
        for output in output_list:
            if output and 'text' in output and AT_BOT in output['text']:
                return output

    return None


def is_valid_command(command):
    """
    Receives messages directed at the Slack bot and returns True if they are valid commands, False otherwise.
    """
    if command.startswith(EXAMPLE_COMMANDS[0]) or command.startswith(EXAMPLE_COMMANDS[1]) \
            and 'https://open.spotify.com/' in command:
        return True
    else:
        return False


def add_reaction(output, reaction):
    """
    Adds emoji reactions (as @music_share user) to messages directed at the Slack bot.
    """
    sc.api_call('reactions.add', name=reaction, channel=output['channel'], timestamp=output['ts'])


def get_url(output):
    """
    Parses Slack message text and returns the Spotify URL.
    """
    words = output['text'].split()
    raw_url = [word for word in words if 'https://open.spotify.com/' in word]
    url = raw_url[0].lstrip('<').rstrip('>')
    return url


def get_spotify_token():
    """
    Gets the Spotify API access token to be passed with requests.
    """
    url = 'https://accounts.spotify.com/api/token'
    payload = {'grant_type': 'client_credentials'}
    r = requests.post(url, data=payload, auth=(CLIENT_ID, CLIENT_SECRET))
    return r.json()['access_token']


def parse_track(track):
    """
    Grabs the title and artist(s) of a Spotify track.
    """
    title = track['name']
    artists = [artist['name'] for artist in track['artists']]
    return title, artists


def get_google_credentials():
    """
    Gets Google Sheets API credentials, or generates new credentials if they don't exist or are invalid.
    """
    scope = 'https://www.googleapis.com/auth/spreadsheets'
    flow = client.flow_from_clientsecrets('client_secret.json', scope, redirect_uri='urn:ietf:wg:oauth:2.0:oob')

    storage = file.Storage('credentials.dat')
    credentials = storage.get()

    if not credentials or credentials.invalid:
        auth_uri = flow.step1_get_authorize_url()
        webbrowser.open(auth_uri)

        auth_code = raw_input('Enter the auth code: ')
        credentials = flow.step2_exchange(auth_code)

        storage.put(credentials)

    return credentials


# def get_service():
#     """Returns an authorised sheets API service? This has not been tested."""
#     credentials = get_google_credentials()
#     http = httplib2.Http()
#     http = credentials.authorize(http)
#     service = discovery.build('sheets', 'v4', http=http)
#
#     return service


def update_spreadsheet(title, artists, url, rating=""):
    """
    Appends a row to the Google spreadsheet with the new track data.
    """
    credentials = get_google_credentials()

    service = discovery.build('sheets', 'v4', credentials=credentials)

    # Cell range to look for existing table to which to append rows
    range_ = 'Charlotte_Recs!A1:F1'

    # How the input data should be interpreted.
    value_input_option = 'USER_ENTERED'

    # How the input data should be inserted.
    insert_data_option = 'INSERT_ROWS'

    # List track artist(s) in a single comma-separated string
    artists = ', '.join(artists)

    value_range_body = {
        'majorDimension': 'ROWS',
        'values': [
            [datetime.date.today().strftime("%-m/%-d/%Y"), title, artists, url, rating]
        ]
    }

    request = service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range=range_,
                                                     valueInputOption=value_input_option,
                                                     insertDataOption=insert_data_option, body=value_range_body)
    response = request.execute()

    return response


def main(sp):
    """
    Does the stuff.
    """
    rtm_output = sc.rtm_read()
    bot_output = parse_rtm_output(rtm_output)

    # bot_output == None if there aren't messages directed at the bot
    if bot_output:

        # This is just the message string after '@music_share' in Slack message
        message = bot_output['text'].split(AT_BOT)[1].strip().lower()
        command = message.split()[0]  # command is either 'share' or 'rate' depending on the Slack message

        if is_valid_command(message):
            # @music_share bot adds an emoji to Slack message sharing the track
            add_reaction(bot_output, 'notes')

            # Get Spotify track URL shared via Slack
            url = get_url(bot_output)

            # Get track data from the Spotify API
            track = sp.track(url)

            # Grab the track title and artist(s)
            title, artists = parse_track(track)

            # Hit Google Sheets API and insert new song data
            r = update_spreadsheet(title, artists, url)
            rows = r['updates']['updatedRows']
            sheet = r['tableRange'].split('!')[0]

            # Respond to the user in Slack
            response = "Successfully appended {0} row(s) to '{1}' sheet!".format(rows, sheet)
            sc.api_call("chat.postMessage", channel=bot_output['channel'], text=response, as_user=True)

        else:
            # If invalid command in the Slack message, respond to the user letting them know
            response = "Not sure what you mean. Use either the *{0}* or *{1}* command with a Spotify link.".format(
                EXAMPLE_COMMANDS[0], EXAMPLE_COMMANDS[1])
            sc.api_call("chat.postMessage", channel=bot_output['channel'], text=response, as_user=True)


if __name__ == "__main__":

    READ_WEBSOCKET_DELAY = 1  # 1 second delay between reading from the Slack RTM firehose

    if sc.rtm_connect():
        print "music_share bot connected and running!"

        # initialize Spotify
        spotify = spotipy.Spotify(auth=get_spotify_token())

        # Spotify token expires after an hour, keep track of the time
        start = time.time()
        while True:
            runtime = time.time() - start
            # If it's been close to an hour, get new Spotify token and reset the start time
            if runtime > 3300:
                spotify = spotipy.Spotify(auth=get_spotify_token())
                start = time.time()
            main(spotify)
            time.sleep(READ_WEBSOCKET_DELAY)

    else:
        print "Connection failed. Invalid Slack token or bot ID?"
