from calendar import c
import json
from math import log
import random
from decimal import Decimal
import os
import re
from typing import Any, Dict, cast
import boto3
import logging
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr, Key
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.decimalDefault import decimal_default
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek


# Helper function to convert Decimal objects to int or float when serializing to JSON.
def correct_picks_value(item: Dict[str, Any]) -> int:
    v = item.get('correctPicks')
    if isinstance(v, dict) and 'N' in v:         # raw Dynamo JSON {"N":"7"}
        return int(v['N'])
    if isinstance(v, Decimal):                    # boto3 returns Decimal
        return int(v)
    try:
        return int(v)                             # already int/str fallback
    except Exception:
        return 0

'''
This function will update user picks to the FBP-Picks DynamoDB table 
for the given email address in the event.
'''
logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger()
logger.info("Initializing SaveFBPPicksPython Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)


cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

pattern = re.compile(r'^[HA]*$')
def isValidPickString(s: str) -> bool:
    if s == "" or s is None:
        return False
    return bool(pattern.match(s))

@app.post("/saveFBPPicks")
def saveFBPPicks():
    fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", "Saving FBP picks", "INFO")
    FBP_PICKS_TABLE_NAME = os.environ.get('FBPPicksTableName', 'FBP-Picks')
    logger.info(f"Using FBP Picks DynamoDB table: {FBP_PICKS_TABLE_NAME}")
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(FBP_PICKS_TABLE_NAME)

    week=getCurrentWeek()
    if week is None:
        fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", "Could not determine current week", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not determine current week'}),
        }
    logger.info(f"Saving picks for week: {week}")
    try:
        body = app.current_event.json_body
        if not isinstance(body, dict):
            raise ValueError("Request body must be a JSON object")
        logger.info(f"Parsed JSON body: {body}")
        email = body.get('email')
        picks = body.get('picks')
        tieBreaker = body.get('tieBreaker')
        

        logger.info(f"Extracted email from API Gateway event: {email}")
        logger.info(f"Extracted picks from API Gateway event: {picks}")
        table.update_item(
            Key={'email': email}, 
            UpdateExpression="SET #picks = :p, #tieBreaker = :t, #week = :w",
            ExpressionAttributeNames={'#picks': 'picks', '#tieBreaker': 'tieBreaker', '#week': 'week'},
            ExpressionAttributeValues={':p': picks, ':t': tieBreaker, ':w': week}
        )

        logger.info(f"Successfully saved picks: {picks} and tieBreaker: {tieBreaker} for email: {email} and week: {week}")
        fbpLog(email, "SaveFBPPicksPython", f"Successfully saved picks: {picks} and tieBreaker: {tieBreaker} for week {week}", "INFO")
    except ClientError as e:
        logger.error(f"DynamoDB Error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", f"DynamoDB Error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'DynamoDB Error'}),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", f"Unexpected error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Unexpected error'}),
        }
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Successfully saved picks: {picks} and tieBreaker: {tieBreaker} for week {week}'}),
    }

@app.post("/validateAndFixFBPPicks")
def validateAndFixFBPPicks():
    fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", "Validating and fixing FBP picks", "INFO")
    FBP_USERS_TABLE_NAME = os.environ.get('FBPUsersTableName', 'FBP-Users')
    FBP_PICKS_TABLE_NAME = os.environ.get('FBPPicksTableName', 'FBP-Picks')
    logger.info(f"Using FBP Picks DynamoDB table: {FBP_PICKS_TABLE_NAME}")
    dynamodb = boto3.resource('dynamodb')
    picksTable = dynamodb.Table(FBP_PICKS_TABLE_NAME)
    usersTable = dynamodb.Table(FBP_USERS_TABLE_NAME)

    week=getCurrentWeek()
    if week is None:
        fbpLog("fbpadmin@my-fbp.com", "SaveFBPPicksPython", "Could not determine current week", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Could not determine current week'}),
        }
    logger.info(f"Validating and fixing picks for week: {week}")
    FBP_SCHEDULE_TABLE_NAME = os.environ.get('FBPScheduleTableName', '2025-Schedule')
    # need to query the schedule table for the week so that I can get the number
    # of games for that week and use it as a limit for the picks string.
    scheduleTable = dynamodb.Table(FBP_SCHEDULE_TABLE_NAME)
    response = scheduleTable.scan(
            FilterExpression=Attr('Week').eq(week)
    )
    schedule = response.get('Items', [])
    if not schedule:
        logger.error(f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table for week {week}")
        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table for week {week}", "ERROR")
        return Response(
            status_code=500,
            body=json.dumps({'error': 'No schedule items found'})
        )
    numberOfGames = len(schedule)
    try:
        # I think you need to get all of the email addrs and loop thru them.
        # table scan seems best.
        # keep the results in a variable the loop thru it.
        noPicks = False
        noTieBreaker = False

        # Now we can get the user and find out what algorithm they are using
        # This will capture the case where the user did not make any picks,
        # or the made SOME picks.  In the second case, the missing pick is
        # shown as a ? in the picks string.  We will replace the ? by applyin the alrorigthm
        # for the user.
        # if the user is using the default algorithm, or we will replace all picks with the default pick for that week if they are using the "pick the winner" algorithm
        #
        # for loop here to loop thru all email addrs.
        email=""
        picks=""
        tieBreaker=""
        algorithm=""
        users=usersTable.scan()
        for user in users.get('Items', []):
            email = user['email']
            logger.info(f"Validating and fixing picks for email: {email}")
            pickResponse = picksTable.get_item(
                Key={'email': email}
            )
            if 'Item' not in pickResponse:
                logger.warning(f"No picks found for email: {email}, skipping validation and fixing for this user")
                fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"No picks found for email: {email}, skipping validation and fixing for this user", level="WARNING")
                continue
            picksItem = pickResponse['Item']
            picks = picksItem.get('picks')
            tieBreaker = picksItem.get('tieBreaker')
            if picks is None:
                noPicks = True
                logger.warning(f"No picks found for email: {email}, setting noPicks flag to True")
                fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"No picks found for email: {email}, setting noPicks flag to True", level="WARNING")
            if tieBreaker is None:
                # tieBreaker will never be None -- it's enforced at the UI.
                # Only when the user does not make picks will we
                # use the default tieBreaker value, which is a random number between 21 and 49.
                noTieBreaker = True
                logger.warning(f"No tieBreaker found for email: {email}, setting noTieBreaker flag to True")
                fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"No tieBreaker found for email: {email}, setting noTieBreaker flag to True", level="WARNING")
            algorithm = user.get('defaultAlgorithm')
            match algorithm:
                case "home":
                    if noPicks:
                        picks = "H" * numberOfGames
                    else:
                        # Replace all ? with H
                        picks = str(picks).replace("?", "H")
                case "away":
                    if noPicks:
                        picks = "A" * numberOfGames
                    else:
                        # Replace all ? with A
                        picks = str(picks).replace("?", "A")
                case "random":
                    defaultPicks = ""
                    if noPicks:
                        for _ in range(numberOfGames):
                            rNumber = random.uniform(0, 1)
                            if rNumber > 0.5:
                                defaultPicks = defaultPicks + "H"
                            else:
                                defaultPicks = defaultPicks + "A"
                        picks = "".join(defaultPicks)
                    else:
                        # Replace all ? with a random pick
                        for i, c in enumerate(str(picks)):
                            if c == "?":
                                rNumber = random.uniform(0, 1)
                                defaultPicks = defaultPicks + (rNumber > 0.5 and "H" or "A")
                            else:
                                defaultPicks = defaultPicks + c
                        picks = defaultPicks
                        logger.info(f"Replaced ? with random picks: {picks}")
                        fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"Replaced ? with random picks: {picks}", level="INFO")
                # For favorites and underdogs we need the schedule from 202X season to determine 
                # which team is the favorite and which is the underdog.
                # We will get the schedule from the DynamoDB table and then apply the
                # algorithm to replace the ? with the correct pick.
                case "favorites":
                    scheduleTable = dynamodb.Table(FBP_SCHEDULE_TABLE_NAME)
                    # Underdog is defined in the DB as either H or A.
                    # Favorite is NOT defined, so scan for it and invert it to get the favorite.
                    response = scheduleTable.scan(
                    FilterExpression=Attr('Week').eq(week)
                    )
                    schedule = response.get('Items', [])
                    if not schedule: 
                        logger.error(f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table")
                        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table", "ERROR")
                        return Response(
                            status_code=500,
                            body=json.dumps({'error': 'No schedule items found'})
                        )
                    if noPicks:
                        # For each game in the schedule, determine the favorite and set the pick
                        defaultPicks = "" 
                        for game in schedule:
                            if game.get('Underdog') == "H":
                                defaultPicks = defaultPicks + "A"
                            elif game.get('Underdog') == "A":
                                defaultPicks = defaultPicks + "H"
                        picks = defaultPicks
                        logger.info(f"Set picks to favorites: {picks}")
                        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Set picks to favorites: {picks}", "INFO") 
                    else:
                        defaultPicks = ""
                        picksFixed = False
                        # Replace all ? with the favorite
                        for i, c in enumerate(str(picks)):
                            if c == "?":
                                picksFixed = True
                                # Find the game in the schedule
                                for game in schedule:
                                    if game.get('Underdog') == "H":
                                        defaultPicks = defaultPicks + "A"
                                    elif game.get('Underdog') == "A":
                                        defaultPicks = defaultPicks + "H"
                        if picksFixed:
                            picks = defaultPicks
                            logger.info(f"Replaced ? with favorites picks: {picks}")
                        fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"Replaced ? with favorites picks: {picks}", level="INFO")
                case "underdogs":
                    scheduleTable = dynamodb.Table(FBP_SCHEDULE_TABLE_NAME)
                    # Underdog is defined in the DB as either H or A.
                    response = scheduleTable.scan(
                    FilterExpression=Attr('Week').eq(week)
                    )
                    schedule = response.get('Items', [])
                    if not schedule:
                        logger.error(f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table")
                        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"No schedule items found in {FBP_SCHEDULE_TABLE_NAME} table", "ERROR")
                        return Response(
                            status_code=500,
                            body=json.dumps({'error': 'No schedule items found'})
                        )
                    if noPicks:
                        defaultPicks = ""
                        for game in schedule:
                            if game.get('Underdog') == "H":
                                defaultPicks = defaultPicks + "H"
                            elif game.get('Underdog') == "A":
                                defaultPicks = defaultPicks + "A"
                        picks = defaultPicks
                        logger.info(f"Set picks to underdogs: {picks}")
                        fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"Set picks to underdogs: {picks}", level="INFO")
                    else:
                        defaultPicks = ""
                        picksFixed = False
                        # Replace all ? with the underdog
                        for i, c in enumerate(str(picks)):
                            if c == "?":
                                picksFixed = True
                                # Find the game in the schedule
                                for game in schedule:
                                    if game.get('Underdog') == "H":
                                        defaultPicks = defaultPicks + "H"
                                    elif game.get('Underdog') == "A":
                                        defaultPicks = defaultPicks + "A"
                        if picksFixed:
                            picks = defaultPicks
                            logger.info(f"Replaced ? with underdog picks: {picks}")
                        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Replaced ? with underdog picks: {picks}", "INFO")                


            defaultTieBreaker = None
            if noPicks:

                userData=usersTable.query(
                    KeyConditionExpression=Key('email').eq(email)
                )
                defaultTieBreaker = userData['Items'][0].get('defaultTieBreaker')  # type: ignore
                if defaultTieBreaker is None:
                    defaultTieBreaker = random.randint(a=21, b=49)
                    logger.info(f"No default tieBreaker found for email: {email}, setting to random number: {defaultTieBreaker}")
                    fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"No default tieBreaker found for email: {email}, setting to random number: {defaultTieBreaker}", level="INFO")
                else:
                    logger.info(f"Extracted default tieBreaker: {defaultTieBreaker} for email: {email}")
                    fbpLog(email=email, action="method: validateAndFixFBPPicks", details=f"Extracted default tieBreaker: {defaultTieBreaker} for email: {email}", level="INFO")
            if noTieBreaker:
                tieBreaker = defaultTieBreaker
            picksTable.update_item(
            Key={'email': email}, 
            UpdateExpression="SET #picks = :p, #tieBreaker = :t, #week = :w",
            ExpressionAttributeNames={'#picks': 'picks', '#tieBreaker': 'tieBreaker', '#week': 'week'},
            ExpressionAttributeValues={':p': picks, ':t': tieBreaker, ':w': week}
            )
            ##
            # You need to reset your noPicks and noTieBreaker flags here for the next user in the loop.
            noPicks = False
            noTieBreaker = False
        # End of for loop to validate and fix picks for each user.  By the time we get here,
        # we should have valid picks and tieBreaker values for each user for the current week.
        logger.info(f"Successfully validated and fixed picks: {picks} and tieBreaker: {tieBreaker} for week {week}")
        fbpLog(email, "SaveFBPPicksPython", f"Successfully validated and fixed picks: {picks} and tieBreaker: {tieBreaker} for week {week}", "INFO")
    except ClientError as e:
        logger.error(f"DynamoDB Error: {e}")
        fbpLog(email="fbpadmin@my-fbp.com", action="method: validateAndFixFBPPicks", details=f"DynamoDB Error: {e}", level="ERROR")
        return{
            'statusCode': 500,
            'body': json.dumps({'error': 'DynamoDB Error'}),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Unexpected error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Unexpected error'}),
        }
    #
    # Now that we've validated and fixed all of the picks, let's see if we have a tie
    # on the number of correct picks.  If so, we need to check against the Monday Night tieBreaker
    # to determin the winner.  If there is still a tie, I think I'll give each player 1/2 of a win.
    #
    try:
        # First, get all picks for the week from the FBP_PICKS_TABLE
        # and put them in a list of dictionaries with the email and picks
        # and tieBreaker fields.
        response = picksTable.scan(
            FilterExpression=Attr('week').eq(week)
        )
        picksList = response.get('Items', [])
        # Now, for each pick in the list, calculate the number of correct picks
        # and store it in the picks dictionary.
        for pick in picksList:
            email = pick['email']
            userPicks = pick['picks']
            correctPicks = 0
            # Get the schedule for the week
            response = scheduleTable.scan(
                FilterExpression=Attr('Week').eq(week)
            )
            schedule = sorted(response.get('Items', []), key=lambda x: str(x['GameId']))

            # For each game in the schedule, compare the user's pick to the actual result
            # and increment the correctPicks counter if the pick is correct.
            for i, game in enumerate(schedule):
                if i < len(str(userPicks)):
                    userPick = str(userPicks)[i]
                    if userPick == game['Winner']:
                        correctPicks += 1
            # Update the picks dictionary with the correct picks
            pick['correctPicks'] = correctPicks
        # Now, sort the picks list by correct picks in descending order
        # End of for loop to calculate correct picks for each user.
        # Now we need to determine if there is a tie for the most correct picks.
        # If so, we need to check the tieBreaker value for each user and compare
        # it to the Monday night total points to determine the winner.
        picksList.sort(key=lambda x: int(cast(Any, x['correctPicks'])), reverse=True)
        logger.info(f"Sorted picks list by correct picks: {picksList}")
        # Now, check if the top two picks have the same number of correct picks
        # If so, check the tieBreaker value for each and see who has the higher value
        # If there is still a tie, we'll give each player 1/2 of a win.
        gameId = ""
        for game in schedule:
            gameId = str(game['GameId'])
            # when you get here, you should have the gameId for the Monday night game.
            # You can use this to get the tieBreaker result from the schedule table and then determine the winner.
        mondayNightGame = scheduleTable.get_item(
            Key={'Week': week, 'GameId': gameId}
        )
        mondayNightTotalPoints = decimal_default(mondayNightGame['Item'].get('AwayScore', 0)) + decimal_default(mondayNightGame['Item'].get('HomeScore', 0))    # type: ignore

        if int(picksList[0]['correctPicks']) == int(picksList[1]['correctPicks']): # type: ignore
            # There is a tie, so check the tieBreaker values
            # The player with the higher tieBreaker value wins
            # If there is still a tie, we'll give each player 1/2 of a win.
            user1tieBreaker = int(picksList[0]['tieBreaker'])   # type: ignore
            user2tieBreaker = int(picksList[1]['tieBreaker'])   # type: ignore
            
            if user1tieBreaker != user2tieBreaker:
                # user1 is closer to the Monday night total points, so user1 wins
                if abs(user1tieBreaker - mondayNightTotalPoints) < abs(user2tieBreaker - mondayNightTotalPoints):
                    # Player 1 wins
                    picksTable.update_item(
                        Key={'email': picksList[0]['email']},
                        UpdateExpression="SET #Winner = :w",
                        ExpressionAttributeNames={'#Winner': 'Winner'},
                        ExpressionAttributeValues={':w': True} 
                    )
                    logger.info(f"Player {picksList[0]['email']} wins the tiebreaker with a tieBreaker of {user1tieBreaker} compared to {user2tieBreaker} and Monday night total points of {mondayNightTotalPoints}.")
                    fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Player {picksList[0]['email']} wins the tiebreaker with a tieBreaker of {user1tieBreaker} compared to {user2tieBreaker} and Monday night total points of {mondayNightTotalPoints}.", "INFO")
                # user2 is closer to the Monday night total points, so user2 wins
                else:
                    # Player 2 wins
                    picksTable.update_item(
                        Key={'email': picksList[1]['email']},
                        UpdateExpression="SET #Winner = :w",
                        ExpressionAttributeNames={'#Winner': 'Winner'},
                        ExpressionAttributeValues={':w': True} 
                    )
                    logger.info(f"Player {picksList[1]['email']} wins the tiebreaker with a tieBreaker of {user2tieBreaker} compared to {user1tieBreaker} and Monday night total points of {mondayNightTotalPoints}.")
                    fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Player {picksList[1]['email']} wins the tiebreaker with a tieBreaker of {user2tieBreaker} compared to {user1tieBreaker} and Monday night total points of {mondayNightTotalPoints}.", "INFO")
            if user1tieBreaker == user2tieBreaker:
                # It's a tie, give each player 1/2 of a win
                picksTable.update_item(
                    Key={'email': picksList[0]['email']},
                    UpdateExpression="SET #Winner = :w",
                    ExpressionAttributeNames={'#Winner': 'Winner'},
                    ExpressionAttributeValues={':w': True} 
                )
                picksTable.update_item(
                    Key={'email': picksList[1]['email']},
                        UpdateExpression="SET #Winner = :w",
                        ExpressionAttributeNames={'#Winner': 'Winner'},
                        ExpressionAttributeValues={':w': True} 
                )
                logger.info(f"Players {picksList[0]['email']} and {picksList[1]['email']} tie with {user1tieBreaker} and Monday night total points of {mondayNightTotalPoints}.")
                fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Players {picksList[0]['email']} and {picksList[1]['email']} tie with {user1tieBreaker} and Monday night total points of {mondayNightTotalPoints}.", "INFO")
    except ClientError as e:
        logger.error(f"DynamoDB Error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"DynamoDB Error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'DynamoDB Error'}),
        }
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        fbpLog("fbpadmin@my-fbp.com", "method: validateAndFixFBPPicks", f"Unexpected error: {e}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Unexpected error'}),
        }
    return {
        'statusCode': 200,
        'body': json.dumps({'message': f'Successfully validated and fixed picks: {picks} and tieBreaker: {tieBreaker} for week {week}'}),
    }


def lambda_handler(event, context):
    return app.resolve(event, context)  