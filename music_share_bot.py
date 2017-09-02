import os
import time
import datetime
import requests
import webbrowser

import spotipy

from slackclient import SlackClient
from googleapiclient import discovery
from oauth2client import client, file
from pprint import pprint


# TODO: Add which Slack user inputted data
# TODO: Allow user to specify a sheet to append to
# TODO: Apple Music API?


# Slack @music_share bot constants
BOT_ID = os.environ.get("BOT_ID")
AT_BOT = "<@" + BOT_ID + ">"
EXAMPLE_COMMANDS = ["share", "rate"]
VALID_USERS = ["ellis", "charlotte"]

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
    if (command.startswith(EXAMPLE_COMMANDS[0]) or command.startswith(EXAMPLE_COMMANDS[1])) and 'https://open.spotify.com/' in command:
        return True
    else:
        return False


def add_reaction(rtm_output, reaction):
    """
    Adds emoji reactions (as @music_share user) to messages directed at the Slack bot.
    """
    sc.api_call('reactions.add', name=reaction, channel=rtm_output['channel'], timestamp=rtm_output['ts'])


def get_url(rtm_output):
    """
    Parses Slack message text and returns the Spotify URL.
    """
    words = rtm_output['text'].split()
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


def get_google_service():
    credentials = get_google_credentials()
    service = discovery.build('sheets', 'v4', credentials=credentials)
    return service


def update_spreadsheet(service, title, artists, url):
    """
    Appends a row to the Google spreadsheet with the new track data.
    """

    # Cell range to look for existing table to which to append rows
    range_ = 'Charlotte_Recs!A1:F1'

    # List track artist(s) in a single comma-separated string
    artists = ', '.join(artists)

    value_range_body = {
        'majorDimension': 'ROWS',
        'values': [
            [datetime.date.today().strftime("%-m/%-d/%Y"), title, artists, url, ""]
        ]
    }

    request = service.spreadsheets().values().append(spreadsheetId=SPREADSHEET_ID, range=range_,
                                                     valueInputOption='USER_ENTERED',insertDataOption='INSERT_ROWS',
                                                     body=value_range_body)
    response = request.execute()

    return response


def verify_rating(rating):
    """
    Checks to see that user entered a valid rating when using the 'rate' command.
    """
    try:
        rating = float(rating)
        if 0 <= rating <= 10:
            return True, rating
        else:
            return False, None
    except ValueError:
        return False, None


def add_rating(service, url, rating):
    """
    Adds (or updates) a rating for an existing track in the spreadsheet.
    """

    # First, read from the spreadsheet to figure out where to post the rating
    url_column = 'Charlotte_Recs!D:D'  # Column in which to look for URL in existing table
    request = service.spreadsheets().values().get(spreadsheetId=SPREADSHEET_ID, range=url_column)
    response = request.execute()

    # Find the appropriate row number
    row = 0
    for cell in response['values']:
        row += 1
        if cell[0] == url:
            break

    # Insert the rating to the spreadsheet
    rating_cell = 'Charlotte_Recs!E{0}'.format(row)
    value = {'values': [[rating]]}
    request = service.spreadsheets().values().update(spreadsheetId=SPREADSHEET_ID, range=rating_cell,
                                                     valueInputOption='USER_ENTERED', body=value)
    response = request.execute()

    return response


def respond_to_user(rtm_output, message):
    """
    Sends a slack message as the bot to the user in the channel in which they messaged the bot.
    """
    sc.api_call('chat.postMessage', channel=rtm_output['channel'], text=message, as_user=True)


def get_user_name(bot_output):
    user_id = bot_output['user']
    response = sc.api_call('users.info', user=user_id)
    if response['ok']:
        return response['user']['name']
    else:
        raise ValueError('Slack API call for user name failed')


def user_validation(user_name):
    return user_name in VALID_USERS


def handle_rate_command(bot_output, message, google_service, track_url, track):

    # Grab the track title and artist(s)
    title, artists = parse_track(track)

    # Get user specified track rating
    rating = message.split()[1]

    # Verify that the user entered a valid rating
    valid, rating = verify_rating(rating)

    # Add valid ratings to the spreadsheet and respond to the user appropriately
    if valid:
        r = add_rating(google_service, track_url, rating)
        if r['updatedCells'] > 0:
            response = "Successfully added rating for {0} to sheet!".format(title)
        else:
            response = "Failed to add rating for {0} to sheet :disappointed:".format(title)
        respond_to_user(bot_output, response)
    else:
        # If invalid rating in the Slack message, respond to the user letting them know
        response = "Not a valid rating. Rating must be a number between 1 and 10 (floats allowed)!"
        respond_to_user(bot_output, response)


def handle_share_command(bot_output, google_service, track_url, track):

    # Grab the track title and artist(s)
    title, artists = parse_track(track)

    # Hit Google Sheets API and insert new song data
    r = update_spreadsheet(google_service, title, artists, track_url)

    rows = r['updates']['updatedRows']
    sheet = r['tableRange'].split('!')[0]
    if rows > 0:
        response = "Successfully appended {0} row(s) to {1} sheet!".format(rows, sheet)
    else:
        response = "Failed to append row(s) to {0} sheet :disappointed:".format(sheet)
    respond_to_user(bot_output, response)


def main(sp):
    """
    Does the stuff.
    """
    # Listen to the Slack output
    rtm_output = sc.rtm_read()
    # Only grab RTM output that is directed at the bot
    bot_output = parse_rtm_output(rtm_output)

    # bot_output is None if there aren't messages directed at the bot
    if bot_output:

        #  Sample bot_output:
        #  {'channel': 'G65LB3LHJ',
        #   'source_team': 'T028G9BR3',
        #   'team': 'T028G9BR3',
        #   'text': "<@U66DH1L87> what's up?",
        #   'ts': '1503871906.000068',
        #   'type': 'message',
        #   'user': 'U1ESNAR42'}

        # Only accept input from known users
        user_name = get_user_name(bot_output)
        is_valid_user = user_validation(user_name)

        if is_valid_user:

            # This is just the message string after '@music_share' in Slack message
            message = bot_output['text'].split(AT_BOT)[1].strip().lower()
            command = message.split()[0]  # command is either 'share' or 'rate' depending on the Slack message

            # Verify that the user sent a valid command to @music_share
            if is_valid_command(message):
                # @music_share bot adds an emoji to Slack message containing the track
                add_reaction(bot_output, 'notes')

                # Get Spotify track URL shared via Slack
                url = get_url(bot_output)

                # Get track data from the Spotify API
                track = sp.track(url)

                # Get Google service for API requests
                service = get_google_service()

                # Handle 'rate' and 'share' user-specified commands
                if command == 'rate':
                    if user_name == "ellis":
                        handle_rate_command(bot_output, message, service, url, track)
                    else:
                        response = "Only *you're boi* can rate tracks, silly!"
                        respond_to_user(bot_output, response)
                else:
                    handle_share_command(bot_output, service, url, track)

            # If invalid command in the Slack message, respond to the user letting them know
            else:
                response = "Not sure what you mean. Use either the *{0}* or *{1}* command with a Spotify link.".format(
                    EXAMPLE_COMMANDS[0], EXAMPLE_COMMANDS[1])
                respond_to_user(bot_output, response)

        # If user is invalid, respond to the user
        else:
            response = "Hey {name}! You're not a user I recognize. Hit up *you're boi* to get credentialed :money_mouth_face:".format(name=user_name.title())
            respond_to_user(bot_output, response)


if __name__ == "__main__":

    read_websocket_delay = 1  # 1 second delay between reading from the Slack RTM firehose

    if sc.rtm_connect():
        print "music_share bot connected and running!"

        # Initialize Spotify
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
            time.sleep(read_websocket_delay)

    else:
        print "Connection failed. Invalid Slack token or bot ID?"
