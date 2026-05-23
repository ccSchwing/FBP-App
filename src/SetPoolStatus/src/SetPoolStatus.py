import json
import boto3
import logging
import os
from botocore.exceptions import ClientError
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib import fbpLog
from fbplib import getCurrentWeek

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

def _set_pool_status(create_next_week, route_name, forced_pool_open=None):
    config_table_name = os.environ.get('FBP_CONFIG_TABLE_NAME', 'FBP-Config')
    week_number = None

    try:
        logger.info(f"[ROUTE] Entered {route_name}")
        logger.info(f"[ROUTE] raw_path={app.current_event.raw_path}, route_key={app.current_event.request_context.route_key}")

        week_number = getCurrentWeek.getCurrentWeek()
        if week_number is None:
            fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "Failed to get current week", "ERROR", "None")
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Failed to get current week'})
            }

        body = app.current_event.json_body
        if forced_pool_open is None:
            if body is None:
                logger.error("No JSON body found in the request")
                fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "No JSON body found in the request", "ERROR", week_number)
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
                fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", "poolOpen must be a boolean (true/false)", "ERROR", week_number)
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
            fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Using forced poolOpen={pool_open} for route {route_name}", "INFO", week_number)
        dynamodb = boto3.resource('dynamodb')
        table = dynamodb.Table(config_table_name)
        response = table.get_item(Key={'Week': week_number})
        if 'Item' not in response:
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'error': f'Configuration for week {week_number} not found',
                    'week': week_number
                })
            }

        current_item = response['Item']
        logger.info(f"Fetched configuration for week {week_number}: {json.dumps(current_item, default=str)}")
        logger.info(f"Current poolOpen value for week {week_number} is: {current_item.get('poolOpen', False)}")
        fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Fetched configuration for week {week_number}: {json.dumps(current_item, default=str)}", "INFO", week_number)
        target_week = week_number + 1 if create_next_week else week_number

        if create_next_week:
            next_week_item = dict(current_item)
            next_week_item['Week'] = target_week
            next_week_item['poolOpen'] = pool_open
            try:
                table.put_item(
                    Item=next_week_item,
                    ConditionExpression='attribute_not_exists(#week)',
                    ExpressionAttributeNames={'#week': 'Week'}
                )
            except ClientError as error:
                if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                    raise

                existing_response = table.get_item(Key={'Week': target_week})
                existing_item = existing_response.get('Item', {})
                existing_pool_open = existing_item.get('poolOpen', False)
                logger.info(f"Week {target_week} already exists; leaving existing poolOpen unchanged at {existing_pool_open}")
                fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Week {target_week} already exists; leaving existing poolOpen unchanged at {existing_pool_open}", "INFO", target_week)
                return {
                    'statusCode': 200,
                    'body': json.dumps({
                        'week': target_week,
                        'poolOpen': existing_pool_open,
                        'message': 'Week already initialized; no update applied'
                    })
                }
        else:
            try:
                updated_config = table.update_item(
                    Key={'Week': target_week},
                    UpdateExpression='SET #poolOpen = :poolOpen',
                    ConditionExpression='attribute_exists(#week)',
                    ExpressionAttributeNames={
                        '#week': 'Week',
                        '#poolOpen': 'poolOpen'
                    },
                    ExpressionAttributeValues={
                        ':poolOpen': pool_open
                    }
                )
                logger.info(f"updatedConfig: {json.dumps(updated_config, default=str)}")
                fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Updated poolOpen value for week {target_week} to: {pool_open}", "INFO", target_week)
            except ClientError as error:
                if error.response.get('Error', {}).get('Code') != 'ConditionalCheckFailedException':
                    raise
                fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Week {target_week} not found; cannot set poolOpen to {pool_open}", "ERROR", target_week)
                logger.error(f"Week {target_week} not found; cannot set poolOpen to {pool_open}")
                return {
                    'statusCode': 404,
                    'body': json.dumps({
                        'week': target_week,
                        'poolOpen': False,
                        'message': 'Week not found; no update applied'
                    })
                }

        response = table.get_item(Key={'Week': target_week})
        logger.info(f"Updated poolOpen value for week {target_week} to: {pool_open}")
        fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Set poolOpen to {pool_open} for week {target_week}", "INFO", target_week)

        if 'Item' in response:
            updated_pool_open = response['Item'].get('poolOpen', False)
            logger.info(f"Returning updated poolOpen value for week {target_week}: {updated_pool_open}")
            return {
                'statusCode': 200,
                'body': json.dumps({
                    'week': target_week,
                    'poolOpen': updated_pool_open
                })
            }
        else:
            logger.error(f"Configuration for week {target_week} not found after update")
            fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Configuration for week {target_week} not found after update", "ERROR", target_week)
            return {
                'statusCode': 404,
                'body': json.dumps({
                    'error': f'Configuration for week {target_week} not found',
                    'week': target_week,
                    'poolOpen': False
                })
            }

    except ClientError as error:
        logger.error(f"DynamoDB Error: {error}")
        fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"DynamoDB Error: {error}", "ERROR", week_number)
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Database error',
                'details': str(error)
            })
        }
    except Exception as error:
        logger.error(f"Unexpected error: {error}")
        fbpLog.fbpLog("fbpadmin@my-fbp.com", "SetPoolStatus", f"Unexpected error: {error}", "ERROR", week_number)
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