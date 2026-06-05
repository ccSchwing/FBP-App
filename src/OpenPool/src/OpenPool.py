import boto3
import json
import os
import logging
from botocore.exceptions import ClientError
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek


# This lamdda function is responsible for all of the work needed to figure out who
# won for the week.
# Step 0:  Make sure the pool is closed for the week that just ended.
# If it is still open, log an error and bail.  We don't want to calculate results while the pool is still open.
# (This should have already been done by the SetPoolStatusClose Lambda, but we can be extra sure here.)
# Calculate the weekly NFL results
# Validate user picks i.e. check for missing picks and make sure all picks are made
#   If there are missing picks, make them using the user's default algorithm.
# Update the weekly results in the database, including wins/losses for each user and determining the weekly winner.
# Send out the weekly results email to all users.
# Open the pool for the next week.
# That should do it.  : -)
def openPool(event, context):
    # Make user that the pool is closed.
    # If not, bail and log an error.
    FBPConfigTableName = os.environ.get("FBPConfigTableName", "FBP-Config")
    configTable = boto3.resource("dynamodb").Table(FBPConfigTableName)
    current_week = getCurrentWeek()
    try:
        response = configTable.get_item(Key={"Week": current_week})
        if "Item" in response:
            pool_open = response["Item"].get("poolOpen", True)
            if pool_open:
                logging.error(
                    f"Pool is still open for week {current_week}. Cannot proceed with opening the pool for the new week."
                )
                fbpLog(
                    "fbpadmin@my-fbp.com",
                    "OpenPool",
                    f"Pool is still open for week {current_week}. Cannot proceed with opening the pool for the new week.",
                    "ERROR",
                )
                return {
                    "statusCode": 400,
                    "body": json.dumps(
                        {
                            "status": "error",
                            "message": f"Pool is still open for week {current_week}. Cannot proceed with opening the pool for the new week.",
                        }
                    ),
                }
            else:
                logging.info(
                    f"Pool is closed for week {current_week}. Proceeding with opening the pool for the new week."
                )
                fbpLog(
                    "fbpadmin@my-fbp.com",
                    "OpenPool",
                    f"Pool is closed for week {current_week}. Proceeding with opening the pool for the new week.",
                    "INFO",
                )
        else:
            logging.error(f"Configuration for current week {current_week} not found.")
            fbpLog(
                "fbpadmin@my-fbp.com",
                "OpenPool",
                f"Configuration for current week {current_week} not found.",
                "ERROR",
            )
            return {
                "statusCode": 404,
                "body": json.dumps(
                    {
                        "status": "error",
                        "message": f"Configuration for current week {current_week} not found.",
                    }
                ),
            }

    except ClientError as e:
        logging.exception(f"Error checking pool status for week {current_week}: {e}")
        fbpLog(
            "fbpadmin@my-fbp.com",
            "OpenPool",
            f"Error checking pool status for week {current_week}: {e}",
            "ERROR",
        )
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Error checking pool status for week {current_week}: {e}",
                }
            ),
        }

    ##
    # Green light.  Let's do this thing.  : -)
    ##
    lambda_client = boto3.client("lambda")
    powertools_event = {
        "version": "2.0",
        "routeKey": "GET /calcWeeklyResults",
        "rawPath": "/calcWeeklyResults",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "body": json.dumps(
            {
                "data": event.get("data", {}),
                "parent_request_id": context.aws_request_id,
                "timestamp": event.get("timestamp"),
            }
        ),
        "requestContext": {
            "routeKey": "GET /calcWeeklyResults",
            "stage": "$default",
            "requestId": "local-request-id",
            "apiId": "local",
            "http": {
                "method": "GET",
                "path": "/calcWeeklyResults",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "sam-local",
            },
        },
        "isBase64Encoded": False,
    }

    calcWeeklyResultsFunction = os.environ.get("CalcWeeklyResults", "CalcWeeklyResults")

    try:
        response = lambda_client.invoke(
            FunctionName=calcWeeklyResultsFunction,
            InvocationType="RequestResponse",
            Payload=json.dumps(powertools_event),
        )
        logging.info(f"Calc Weekly Results Response: {response}")
        result = json.loads(response["Payload"].read())
        logging.info(f"Calc Weekly Results Result: {result}")
        if result.get("statusCode") == 200:
            body = result.get("body")
            logging.info(f"Calc Weekly Results Body: {body}")
            if isinstance(body, str):
                body = json.loads(body)
            if result.get("statusCode") == 200:
                logging.info(f"Calc Weekly Results Body: {body}")
                logging.info("Calc Weekly Results succeeded, proceeding to next steps.")
                # Here you would add the logic to invoke the next Lambda functions for emailing users, updating pool status, etc.
        else:
            logging.error(
                f"Calc Weekly Results failed with status code: {result.get('statusCode')}"
            )
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "status": "error",
                        "message": f"Calc Weekly Results failed with status code: {result.get('statusCode')}",
                        "details": result.get("body", {}),
                    }
                ),
            }
    except ClientError as e:
        logging.exception(f"Error invoking Calc Weekly Results Lambda: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Error invoking Calc Weekly Results Lambda: {e}",
                    "details": str(e),
                }
            ),
        }
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Unexpected error: {e}",
                    "details": str(e),
                }
            ),
        }

    # Second, validate and set fbp picks for the week by invoking the SaveFBPPicks Lambda function.
    # There is a /validateAndFixPicks entrypoint in SaveFBPPicks.

    powertools_event = {
        "version": "2.0",
        "routeKey": "POST /validateAndFixFBPPicks",
        "rawPath": "/validateAndFixFBPPicks",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "body": "{}",
        "requestContext": {
            "routeKey": "POST /validateAndFixPicks",
            "stage": "$default",
            "requestId": "local-request-id",
            "apiId": "local",
            "http": {
                "method": "POST",
                "path": "/validateAndFixPicks",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "sam-local",
            },
        },
        "isBase64Encoded": False,
    }

    # Get the Lambda function name from environment variable or use a default value
    saveFBPPicksFunction = os.environ.get("SaveFBPPicks", "SaveFBPPicks")
    logging.info(
        f"Invoking SaveFBPPicks Lambda function: {saveFBPPicksFunction} with event: {powertools_event}"
    )
    try:
        response = lambda_client.invoke(
            FunctionName=saveFBPPicksFunction,
            InvocationType="RequestResponse",
            Payload=json.dumps(powertools_event),
        )
        logging.info(f"SaveFBPPicks Response: {response}")
        result = json.loads(response["Payload"].read())
        logging.info(f"SaveFBPPicks Result: {result}")
        if result.get("statusCode") == 200:
            body = result.get("body")
            logging.info(f"SaveFBPPicks Body: {body}")
            if isinstance(body, str):
                body = json.loads(body)
            if result.get("statusCode") == 200:
                logging.info(f"SaveFBPPicks Body: {body}")
                logging.info("SaveFBPPicks succeeded, proceeding to next steps.")
                # Here you would add the logic to invoke the next Lambda functions for emailing users, updating pool status, etc.
        else:
            logging.error(
                f"SaveFBPPicks failed with status code: {result.get('statusCode')}"
            )
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "status": "error",
                        "message": f"SaveFBPPicks failed with status code: {result.get('statusCode')}",
                        "details": result.get("body", {}),
                    }
                ),
            }
    except ClientError as e:
        logging.exception(f"Error invoking SaveFBPPicks Lambda: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Error invoking SaveFBPPicks Lambda: {e}",
                    "details": str(e),
                }
            ),
        }
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Unexpected error: {e}",
                    "details": str(e),
                }
            ),
        }
    # Third, UpdateWeeklyResults -- this one will update the user's wins/losses and determine the
    # weekly winner.

    powertools_event = {
        "version": "2.0",
        "routeKey": "GET /updateWeeklyResults",
        "rawPath": "/updateWeeklyResults",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "body": json.dumps(
            {
                "data": event.get("data", {}),
                "parent_request_id": context.aws_request_id,
                "timestamp": event.get("timestamp"),
            }
        ),
        "requestContext": {
            "routeKey": "GET /updateWeeklyResults",
            "stage": "$default",
            "requestId": "local-request-id",
            "apiId": "local",
            "http": {
                "method": "GET",
                "path": "/updateWeeklyResults",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "sam-local",
            },
        },
        "isBase64Encoded": False,
    }

    updateWeeklyResultsFunction = os.environ.get(
        "UpdateWeeklyResults", "UpdateWeeklyResults"
    )
    logging.info(
        f"Invoking UpdateWeeklyResults Lambda function: {updateWeeklyResultsFunction}"
    )
    try:
        response = lambda_client.invoke(
            FunctionName=updateWeeklyResultsFunction,
            InvocationType="RequestResponse",
            Payload=json.dumps(powertools_event),
        )
        logging.info(f"UpdateWeeklyResults Response: {response}")
        result = json.loads(response["Payload"].read())
        logging.info(f"UpdateWeeklyResults Result: {result}")
        if result.get("statusCode") == 200:
            body = result.get("body")
            logging.info(f"UpdateWeeklyResults Body: {body}")
            if isinstance(body, str):
                body = json.loads(body)
            if result.get("statusCode") == 200:
                logging.info(f"UpdateWeeklyResults Body: {body}")
                logging.info("UpdateWeeklyResults succeeded, proceeding to next steps.")
                # Here you would add the logic to invoke the next Lambda functions for emailing users, updating pool status, etc.
        else:
            logging.error(
                f"UpdateWeeklyResults failed with status code: {result.get('statusCode')}"
            )
            return {
                "statusCode": 500,
                "body": json.dumps(
                    {
                        "status": "error",
                        "message": f"UpdateWeeklyResults failed with status code: {result.get('statusCode')}",
                        "details": result.get("body", {}),
                    }
                ),
            }
    except ClientError as e:
        logging.exception(f"Error invoking UpdateWeeklyResults Lambda: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Error invoking UpdateWeeklyResults Lambda: {e}",
                    "details": str(e),
                }
            ),
        }
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"Unexpected error: {e}",
                    "details": str(e),
                }
            ),
        }

    ## Call SendEmail Lambda to send out the weekly results to all users.
    def create_email_event(email_data):

        return {
            "version": "2.0",
            "routeKey": "POST /sendEmail",
            "rawPath": "/sendEmail",
            "rawQueryString": "",
            "headers": {"content-type": "application/json"},
            "body": json.dumps(email_data),
            "requestContext": {
                "http": {
                    "method": "POST",
                    "path": "/sendEmail",
                    "protocol": "HTTP/1.1",
                    "sourceIp": "127.0.0.1",
                    "userAgent": "sam-local",
                },
                "routeKey": "POST /sendEmail",
                "stage": "$default",
            },
            "isBase64Encoded": False,
        }

    sendEmailFunction = os.environ.get("SendEmail", "SendEmail")

    # I think I only need the template name
    # email and firstname are picked up in SendEmail lambda.
    email_data = {"templateName": "FBPWeeklyWinner"}
    sendEmailEvent = create_email_event(email_data)

    response = lambda_client.invoke(
        FunctionName=sendEmailFunction,
        InvocationType="RequestResponse",
        Payload=json.dumps(sendEmailEvent),
    )
    logging.info(f"SendEmail Response: {response}")
    fbpLog("fbpadmin@my-fbp.com", "openPool", f"SendEmail Response: {response}", "INFO")

    setPoolOpenFunction = os.environ.get("SetPoolStatusOpen", "SetPoolStatusOpen")
    powertools_event = {
        "version": "2.0",
        "routeKey": "POST /setPoolStatusOpen",
        "rawPath": "/setPoolStatusOpen",
        "rawQueryString": "",
        "headers": {"content-type": "application/json"},
        "body": '{"poolOpen": true, "create_next_week": true}',
        "requestContext": {
            "routeKey": "POST /setPoolStatusOpen",
            "stage": "$default",
            "requestId": "local-request-id",
            "apiId": "local",
            "http": {
                "method": "POST",
                "path": "/setPoolStatusOpen",
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "sam-local",
            },
        },
        "isBase64Encoded": False,
    }
    response = lambda_client.invoke(
        FunctionName=setPoolOpenFunction,
        InvocationType="RequestResponse",
        Payload=json.dumps(powertools_event),
    )
    if response.get("StatusCode") == 200:
        logging.info(
            f"SetPoolStatusOpen succeeded, pool is now open for the new week: {response.get('week')}."
        )
        fbpLog(
            "fbpadmin@my-fbp.com",
            "openPool",
            f"SetPoolStatusOpen succeeded, pool is now open for the new week: {response.get('week')}.",
            "INFO",
        )
    else:
        logging.error(
            f"SetPoolStatusOpen failed with status code: {response.get('StatusCode')}"
        )
        return {
            "statusCode": 500,
            "body": json.dumps(
                {
                    "status": "error",
                    "message": f"SetPoolStatusOpen failed with status code: {response.get('StatusCode')}",
                    "details": (
                        response.get("Payload").read().decode("utf-8")
                        if response.get("Payload")
                        else {}
                    ),
                }
            ),
        }
    return {
        "statusCode": 200,
        "body": json.dumps(
            {
                "status": "success",
                "message": "Pool opened successfully",
                "details": {
                    "poolOpen": True,
                    "week": response.get("week"),
                },
            }
        ),
    }
