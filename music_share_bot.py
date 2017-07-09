import os
import time
from slackclient import SlackClient

# music_share bot's ID as an environment variable
BOT_ID = os.environ.get("BOT_ID")

# constants
AT_BOT = "<@" + BOT_ID + ">"
EXAMPLE_COMMAND = "share"

# instantiate Slack & Twilio clients
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
    Receives commands directed at the bot and returns True if they are valid commands, False otherwise.
    """
    if command.startswith(EXAMPLE_COMMAND):
        return True
    else:
        return False


def add_reaction(output):
    sc.api_call(
        'reactions.add',
        name='thumbsup',
        channel=output['channel'],
        timestamp=output['ts']
    )


def main():
    rtm_output = sc.rtm_read()
    bot_output = parse_rtm_output(rtm_output)
    # bot_output == None if there aren't messages directed at the bot
    if bot_output:
        if is_valid_command(bot_output['text'].split(AT_BOT)[1].strip().lower()):
            print 'valid bot output!'
            add_reaction(bot_output)
        else:
            response = "Not sure what you mean. Use the *{0}* command with a Spotify link.".format(EXAMPLE_COMMAND)
            sc.api_call("chat.postMessage", channel=bot_output['channel'], text=response, as_user=True)


if __name__ == "__main__":

    READ_WEBSOCKET_DELAY = 1  # 1 second delay between reading from firehose

    if sc.rtm_connect():
        print("music_share bot connected and running!")
        while True:
            main()
            time.sleep(READ_WEBSOCKET_DELAY)
    else:
        print("Connection failed. Invalid Slack token or bot ID?")
