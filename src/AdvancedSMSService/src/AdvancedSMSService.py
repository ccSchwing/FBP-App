import os
import json
import boto3
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()
metrics = Metrics()

class SMSType(Enum):
    WELCOME = "welcome"
    REMINDER = "reminder"

@dataclass
class SMSRequest:
    sms_type: SMSType
    recipient: str
    data: Dict[str, Any]
    sender_name: Optional[str] = None

class AdvancedSMSService:
    """Advanced SMS service with multiple SMS types"""

    def __init__(self):
        secrets = self._get_secrets()
        self.sms_client = Client(secrets['TWILIO_ACCOUNT_SID'], secrets['TWILIO_AUTH_TOKEN'])
        self.default_sender = secrets['TWILIO_PHONE_NUMBER']
        self.company_name = os.environ.get('COMPANY_NAME', 'FBP')
        self.fbpHomeUrl = os.environ.get('BASE_URL', 'https://my-fbp.com')
    def _get_secrets(self) -> dict:
        client = boto3.client('secretsmanager')
        # Twilio Secret has the account SID, auth token, and phone number stored as a JSON string
        response = client.get_secret_value(SecretId=os.environ['TWILIO_SECRET'])
        return json.loads(response['SecretString']) 
    

    @tracer.capture_method
    def send_sms(self, sms_request: SMSRequest) -> str:
        """Route SMS sending based on type"""
        
        sms_handlers = {
            SMSType.WELCOME: self._send_welcome_sms,
            SMSType.REMINDER: self._send_reminder_sms
        }
        
        handler = sms_handlers.get(sms_request.sms_type)
        if not handler:
            raise ValueError(f"Unsupported SMS type: {sms_request.sms_type}")
        
        return handler(sms_request)
    
    def _send_welcome_sms(self, request: SMSRequest) -> str:
        """Send welcome SMS"""
        user_name = request.data.get('user_name', 'User')
        text_content = f"""
        Welcome to {self.company_name}!
        
        Hi {user_name},
        Your account has been successfully created.
        Best regards,
        The {self.company_name} Team
        """
        
        return self._send_sms(
            recipient=request.recipient,
            text_content=text_content,
            sms_type="welcome"
        )
    
    def _send_reminder_sms(self, request: SMSRequest) -> str:
        """Send reminder SMS"""
        user_name = request.data.get('user_name', 'User')
        
        text_content = f"""
        Hi {user_name},
        FBP is now open for picks.  See: {self.fbpHomeUrl}
        Best regards,
        The {self.company_name} Team
        """
        
        return self._send_sms(
            recipient=request.recipient,
            text_content=text_content,
            sms_type="reminder"
        )

    @tracer.capture_method
    def _send_sms(self, recipient: str, text_content: str, sms_type: str) -> str:
        try:
            message = self.sms_client.messages.create(
                body=text_content,
                from_=self.default_sender,
                to=recipient
            )
            
            logger.info("SMS sent successfully", extra={
                "message_sid": message.sid,
                "recipient": recipient,
                "sms_type": sms_type
            })
            
            metrics.add_metric(name="SMSSent", unit=MetricUnit.Count, value=1)
            metrics.add_metadata(key="sms_type", value=sms_type)

            return "SMS sent with to:" + recipient
            
        except Exception as e:
            logger.error("Failed to send SMS", extra={
                "error": str(e),
                "recipient": recipient,
                "sms_type": sms_type
            })
            
            metrics.add_metric(name="SMSErrors", unit=MetricUnit.Count, value=1)
            metrics.add_metadata(key="sms_type", value=sms_type)
            metrics.add_metadata(key="error_message", value=str(e))
            
            raise


sms_service = AdvancedSMSService()

@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Lambda handler for SMS sending"""
    
    try:
        body = json.loads(event.get('body', '{}'))
        
        # Create SMS request
        sms_request = SMSRequest(
            sms_type=SMSType(body.get('sms_type')),
            recipient=body.get('recipient'),
            data=body.get('data', {}),
            sender_name=os.environ.get('COMPANY_NAME', 'FBP')
        )
        
        # Send SMS
        message_id = sms_service.send_sms(sms_request)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{sms_request.sms_type.value} SMS sent successfully',
                'message_id': message_id
            })
        }
        
    except ValueError as e:
        logger.error("Invalid request", extra={"error": str(e)})
        return {
            'statusCode': 400,
            'body': json.dumps({'error': str(e)})
        }
    
    except TwilioRestException as e:
        logger.error("Twilio error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Failed to send SMS',
                'details': str(e)
            })
        }
    
    except Exception as e:
        logger.error("Unexpected error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
