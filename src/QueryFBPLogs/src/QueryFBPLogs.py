import json
import os
import boto3
import logging
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver, Response
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek
from fbplib.decimalDefault import decimal_default

logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger("QueryFBPLogs")
logger.info("Initializing QueryFBPLogs Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)


CONFIG_TABLE_NAME = os.environ.get('FBPConfigTableName', 'FBP-Config')
LOGS_TABLE_NAME = os.environ.get('FBPLogsTableName', '2025-Log')
logger.info(f"Using DynamoDB tables - Config: {CONFIG_TABLE_NAME}, Logs: {LOGS_TABLE_NAME}")

cors_config = CORSConfig(
allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
max_age=86400,  # Cache preflight for 24 hours
 allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

@app.post("/queryFBPLogs")
def query_fbp_logs():
    logger.info("Handling queryFBPLogs request")  # Log entry into the function
    try:
        request_body = app.current_event.json_body
        logger.info(f"Request body: {request_body}")
        if not request_body:
            logger.error("No JSON body found in the request")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({
                    'error': 'Invalid request body',
                    'message': 'Request body seems to be empty or not valid JSON'
                })
            )
        startDate = request_body.get('startDate')
        if startDate is None:
            logger.error("startDate is missing from the request body")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({
                    'error': 'Missing startDate',
                    'message': 'startDate is required in the request body'
                })
            )
        endDate = request_body.get('endDate')
        if endDate is None:
            logger.error("endDate is missing from the request body")
            return Response(
                status_code=400,
                content_type="application/json",
                body=json.dumps({
                    'error': 'Missing endDate',
                    'message': 'endDate is required in the request body'
                })
            )
        logger.info(f"Extracted startDate: {startDate}, endDate: {endDate} from API Gateway event")
        week = request_body.get('week')
        if week is None:
            week = getCurrentWeek()
            logger.info(f"week is not provided in the request body, using current week: {week}")
        else:
            logger.info(f"Extracted week: {week} from API Gateway event")
            logger.info(f"Extracted startDate: {startDate}, endDate: {endDate}, week: {week} from API Gateway event")
        logLevel = request_body.get('logLevel')
        if logLevel is None:
            logLevel = "INFO"
            logger.info(f"logLevel is not provided in the request body, using default logLevel: {logLevel}")
        else:
            logger.info(f"Extracted logLevel: {logLevel} from API Gateway event")
            logger.info(f"Extracted startDate: {startDate}, endDate: {endDate}, week: {week}, logLevel: {logLevel} from API Gateway event")

        logTable = boto3.resource('dynamodb').Table(LOGS_TABLE_NAME)

        # Get all logs regardless of logLevel or filter by logLevel if provideod
        # Do we care about what week it is?  I don't think so.
        if logLevel == "ALL":
            response = logTable.scan(
                FilterExpression="#ts BETWEEN :startDate AND :endDate",
                ExpressionAttributeNames={"#ts": "timestamp"},
                ExpressionAttributeValues={
                    ":startDate": startDate,
                    ":endDate": endDate
                }
            )
            items = response.get('Items', [])
            logger.info(f"Query returned {len(items)} log entries")
            logger.info(f"Log entries: {json.dumps(items, default=decimal_default)}")
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps(items, default=decimal_default)
            )
        else:
            response = logTable.query(
                KeyConditionExpression="#lvl = :logLevel AND #ts BETWEEN :startDate AND :endDate",
                FilterExpression="week = :week",
                ExpressionAttributeNames={
                    "#ts": "timestamp",
                    "#lvl": "level"
                },
                ExpressionAttributeValues={
                    ":logLevel": logLevel,
                    ":startDate": startDate,
                    ":endDate": endDate,
                    ":week": week
                }
            )
            items = response.get('Items', [])
            logger.info(f"Query returned {len(items)} log entries")
            logger.info(f"Log entries: {json.dumps(items, default=decimal_default)}")
            return Response(
                status_code=200,
                content_type="application/json",
                body=json.dumps(items, default=decimal_default)
            )
    except Exception as e:
        logger.error(f"Error parsing request body: {e}")
        return Response(
            status_code=400,
            content_type="application/json",
            body=json.dumps({
                'error': 'Invalid request body',
                'message': f"Error parsing request body: {str(e)}"
            })
        )
def lambda_handler(event, context):
    return app.resolve(event, context) 