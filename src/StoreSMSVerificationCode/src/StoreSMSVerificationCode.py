import json
import os
import random
import re
import boto3
import logging
import hashlib
from botocore.exceptions import ClientError
from boto3.dynamodb.conditions import Attr
from aws_lambda_powertools.event_handler import APIGatewayHttpResolver
from aws_lambda_powertools.event_handler.api_gateway import CORSConfig
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek

logger = logging.getLogger()
logger.info("Initializing GetWeeklyResults Lambda function")  # Log initialization message
logger.setLevel(logging.INFO)

cors_config = CORSConfig(
    allow_origin="*",  # Or specify your domain like "https://yourdomain.com"
    allow_headers=["Content-Type", "X-Amz-Date", "Authorization", "X-Api-Key", "X-Amz-Security-Token"],
    max_age=86400,  # Cache preflight for 24 hours
    allow_credentials=False
)

app=APIGatewayHttpResolver(cors=cors_config)

@app.post("/storeSMSVerificationCode")
def storeVerificationCode():

    ##
    # get the mobile number from the event body
    ##
    event_body = app.current_event.json_body
    email=event_body.get("email")
    if email is None:
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Email is required'}),
        }
    mobile_number = event_body.get("mobile_number")
    if mobile_number is None:
        return {
            'statusCode': 500,
            'body': json.dumps({'message': '10 Digit Mobile number is required'}),
        }
    ##
    # length of mobile_number should be 10
    ##
    if len(mobile_number) != 10:
        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Mobile number must be 10 digits'}),
        }
    
    ##
    # generate a 6 digit random number
    ##

    verification_code = random.randint(100000, 999999)
    print(f"Generated verification code: {verification_code}")
    ##
    # Convert verification_code to string
    ##
    verification_code = str(verification_code)

    ##
    # Generate a hash of the verification_code
    ##

    verification_code_hash = hashlib.sha256(verification_code.encode()).hexdigest()
    print(f"Generated verification code hash: {verification_code_hash}")

    ##
    # Store pending mobile number and verification code hash in DynamoDB
    ##
    try:
        dynamodb = boto3.resource('dynamodb')
        FBP_USERS_TABLE=os.environ.get('FBPUsersTableName')
        usersTable = dynamodb.Table(FBP_USERS_TABLE)
        usersTable.update_item(
            Key={'email': email},
            UpdateExpression="SET pending_mobile_number = :mobile_number, verification_code_hash = :verification_code_hash",
            ExpressionAttributeValues={
                ':mobile_number': mobile_number,
                ':verification_code_hash': verification_code_hash
            }
        )
        return {
            'statusCode': 200,
            'body': json.dumps({'verification_code_hash': verification_code_hash}),
        }
    except Exception as e:

        return {
            'statusCode': 500,
            'body': json.dumps({'message': 'Could not store verification code', 'error': str(e)}),
        }





def lambda_handler(event, context):
    return app.resolve(event, context)  