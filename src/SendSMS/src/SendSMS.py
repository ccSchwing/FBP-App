import boto3
import json
import logging
import os
from datetime import datetime
from botocore.exceptions import ClientError
from fbplib.fbpLog import fbpLog

logger = logging.getLogger()
logger.setLevel(logging.INFO)

notify_client = boto3.client('pinpoint-sms-voice-v2')

def lambda_handler(event, context):
    """
    Application State Alert System using AWS End User Messaging Notify
    """
    
    # Environment variables
    NOTIFY_CONFIG_ID = os.environ.get('NOTIFY_CONFIG_ID')
    DEFAULT_PHONE = os.environ.get('DEFAULT_PHONE_NUMBER')
    
    # Alert type mapping to templates and codes
    ALERT_TEMPLATES = {
        'FBP-Test-Alert': {
            'template_id': 'notify-code-verification-english-001',
            'code_prefix': 'TEST'
        },
        'SYSTEM_DOWN': {
            'template_id': 'notify-code-verification-english-001',
            'code_prefix': 'SYS'
        },
        'HIGH_ERROR_RATE': {
            'template_id': 'notify-code-verification-english-001', 
            'code_prefix': 'ERR'
        },
        'DEPLOYMENT_SUCCESS': {
            'template_id': 'notify-code-verification-english-001',
            'code_prefix': 'DEP'
        },
        'PERFORMANCE_WARNING': {
            'template_id': 'notify-code-verification-english-001',
            'code_prefix': 'PERF'
        }
    }
    
    try:
        # Parse the incoming event
        alert_type = event.get('alert_type', 'SYSTEM_ALERT')
        severity = event.get('severity', 'INFO')  # INFO, WARN, ERROR, CRITICAL
        message = event.get('message', 'Application alert')
        phone_numbers = event.get('phone_numbers', [DEFAULT_PHONE])
        
        # Generate alert code based on type and timestamp
        timestamp = datetime.now().strftime('%H%M')
        template_config = ALERT_TEMPLATES.get(alert_type, ALERT_TEMPLATES['SYSTEM_DOWN'])
        alert_code = f"{template_config['code_prefix']}{timestamp}"
        
        results = []
        
        # Send to all specified phone numbers
        for phone in phone_numbers:
            if not phone:
                continue
                
            try:
                response = notify_client.send_notify_text_message(
                    NotifyConfigurationId=NOTIFY_CONFIG_ID,
                    DestinationPhoneNumber=phone,
                    TemplateId=template_config['template_id'],
                    TemplateVariables={
                        'code': alert_code
                    },
                    Context={
                        'alert_type': alert_type,
                        'severity': severity,
                        'timestamp': datetime.now().isoformat()
                    }
                )
                
                results.append({
                    'phone': phone,
                    'status': 'success',
                    'messageId': response['MessageId'],
                    'resolvedBody': response.get('ResolvedMessageBody')
                })
                
                logger.info(f"Alert sent to {phone}. MessageId: {response['MessageId']}")
                
            except ClientError as e:
                fbpLog(email="fbpadmin@my-fbp.com", action="SendSMS", details=f"Failed to send SMS to {phone}: {e}", level="ERROR")
                results.append({
                    'phone': phone,
                    'status': 'failed',
                    'error': str(e)
                })
                logger.error(f"Failed to send alert to {phone}. Error: {e}")
         
