import json
import boto3
import logging
import os
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek

logging.basicConfig(format='%(levelname)s %(message)s')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)


app = APIGatewayHttpResolver(cors=cors_config)


def parse_pool_open(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "y"):
            return True
        if lowered in ("false", "0", "no", "n"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return None

# If create_next_week is False, this function will update the poolOpen value for the current week.
# If create_next_week is True, this function will create a new entry for the next week
def _set_pool_status(create_next_week, route_name, forced_pool_open=None):
    config_table_name = os.environ.get('FBP_CONFIG_TABLE_NAME', 'FBP-Config')
    week_number = None

    try:
        logger.info(f"[ROUTE] Entered {route_name}")
        logger.info(f"[ROUTE] raw_path={app.current_event.raw_path}, route_key={app.current_event.request_context.route_key}")

        week_number = getCurrentWeek()
        if week_number is None:
            fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "Failed to get current week", "ERROR")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get current week'})
            }

        body = app.current_event.json_body
        if forced_pool_open is None:
            if body is None:
                logger.error("No JSON body found in the request")
                fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "No JSON body found in the request", "ERROR")
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'error': 'Invalid request',
                        'message': 'Request body must be a valid JSON'
                    })
                }

            pool_open = parse_pool_open(body.get('poolOpen'))
            logger.info(f"Received request body: {body}, parsed poolOpen: {pool_open}")
            if pool_open is None:
                fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "poolOpen must be a boolean (true/false)", "ERROR")
                return {
                    'statusCode': 400,
                    'body': json.dumps({
                        'error': 'Invalid request',
                        'message': 'poolOpen must be a boolean (true/false)'
                    })
                }
        else:
            pool_open = forced_pool_open
            logger.info(f"Using forced poolOpen={pool_open} for route {route_name}")
            fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Using forced poolOpen={pool_open} for route {route_name}", "INFO")
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(config_table_name)
        # add new record for next week with poolOpen value, week_number + 1, and resultsCalculated = false
        if create_next_week and week_number is not None:
            logger.info(f"Creating new entry for next week: {week_number + 1}")
            fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Creating new entry for next week: {week_number + 1}", "INFO")
            next_week_item = {
                'Week': week_number + 1,
                'poolOpen': pool_open,
                'resultsCalculated': False
            }
            try:
                table.put_item(Item=next_week_item)
                logger.info(f"Created new entry for next week: {week_number + 1} with poolOpen={pool_open}")
                fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Created new entry for next week: {week_number + 1} with poolOpen={pool_open}", "INFO")
            except ClientError as error:
                logger.error(f"Error creating entry for next week: {error}")
                fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Error creating entry for next week: {error}", "ERROR")
                return {
                    'statusCode': 500,
                    'body': json.dumps({
                        'error': 'Database error',
                        'details': str(error)})
                }
        week=getCurrentWeek()
        response = table.get_item(Key={'Week': week})
        logger.info(f"Updated poolOpen value for week {week} to: {pool_open}")
        fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Set poolOpen to {pool_open} for week {week}", "INFO")

        if 'Item' in response:
            updated_pool_open = response['Item'].get('poolOpen', False)
            logger.info(f"Returning updated poolOpen value for week {week}: {updated_pool_open}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'week': week,
                    'poolOpen': updated_pool_open,
                    'resultsCalculated': response['Item'].get('resultsCalculated', False)
                })
            }
        else:
            logger.error(f"Configuration for week {week} not found after update")
            fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Configuration for week {week} not found after update", "ERROR")
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'error': f'Configuration for week {week} not found',
                    'week': week,
                    'poolOpen': False
                })
            }

    except ClientError as error:
        logger.error(f"DynamoDB Error: {error}")
        fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"DynamoDB Error: {error}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Database error',
                'details': str(error)
            })
        }
    except Exception as error:
        logger.error(f"Unexpected error: {error}")
        fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Unexpected error: {error}", "ERROR")
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Internal server error'
            })
        }


@app.post("/setPoolStatusOpen")
def setPoolStatusOpen():
    return _set_pool_status(create_next_week=True, route_name="setPoolStatusOpen", forced_pool_open=True)


@app.post("/setPoolStatusClosed")
def setPoolStatusClosed():
    return _set_pool_status(create_next_week=False, route_name="setPoolStatusClosed")



def lambda_handler(event, context):
    return app.resolve(event, context)