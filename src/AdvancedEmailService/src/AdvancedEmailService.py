import json
import boto3
import os
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass, asdict
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()
metrics = Metrics()

class EmailType(Enum):
    WELCOME = "welcome"
    # Add more email types as you migrate from templates...

@dataclass
class EmailResponse:
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None
    email_type: Optional[str] = None
    recipient: Optional[str] = None

class EmailService:
    """Production email service for Lambda chaining"""
    
    def __init__(self):
        self.ses_client = boto3.client('ses')
        self.default_sender = os.environ.get('FromEmail', 'fbpadmin@my-fbp.com')
        self.company_name = os.environ.get('CompanyName', 'FBP')
        self.base_url = os.environ.get('BaseUrl', 'https://www.my-fbp.com')
        self.support_email = os.environ.get('SupportEmail', 'fbpadmin@my-fbp.com')
    
    @tracer.capture_method
    def send_email(self, email_type: str, recipient: str, data: Dict[str, Any], 
                   reply_to: Optional[str] = None, 
                   tags: Optional[Dict[str, str]] = None) -> EmailResponse:
        """Main entry point for sending emails"""
        
        try:
            # Validate inputs
            if not recipient or '@' not in recipient:
                raise ValueError("Valid recipient email is required")
            
            if not data:
                data = {}
            
            # Get email content generator
            content_generator = self._get_content_generator(EmailType(email_type))
            
            # Generate email content
            subject, html_content, text_content = content_generator(data)
            
            # Send via SES
            message_id = self._send_ses_email(
                recipient=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                reply_to=reply_to,
                tags=tags,
                email_type=email_type
            )
            
            return EmailResponse(
                success=True,
                message_id=message_id,
                email_type=email_type,
                recipient=recipient
            )
            
        except Exception as e:
            logger.error("Failed to send email", extra={
                "error": str(e),
                "email_type": email_type,
                "recipient": recipient
            })
            
            return EmailResponse(
                success=False,
                error=str(e),
                email_type=email_type,
                recipient=recipient
            )
    
    def _get_content_generator(self, email_type: EmailType):
        """Get the appropriate content generator for email type"""
        
        generators = {
            EmailType.WELCOME: self._generate_welcome_content,
            # Add more generators as you migrate from templates...
        }
        
        generator = generators.get(email_type)
        if not generator:
            raise ValueError(f"Unsupported email type: {email_type.value}")
        
        return generator
    
    def _generate_welcome_content(self, data: Dict[str, Any]) -> tuple:
        """Generate welcome email content"""
        user_name = data.get('user_name', 'User')
        activation_link = data.get('activation_link', f'{self.base_url}/activate')
        
        subject = f"Welcome to FBP -- Your Account is Ready"
        
        html_content = f"""
        <html>
        <body>
            <h1>Welcome to {self.company_name}, {user_name}!</h1>
            <p>We're thrilled to have you join our community! Your account has been created successfully.</p>
            <p>Quick Start Guide:</p>
            <ul>
                <li>Activate your account: <a href="{activation_link}">Activate</a></li>
                <li>Complete your profile setup</li>
                <li>Explore our features and tools</li>
            </ul>
            <p>Need help? Contact us at <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body>
        </html>
        """
        
        text_content = f"""
Hello {user_name} --\n\nWelcome to {self.company_name}! Your {self.company_name} account has been successfully created.\n\n
Next Steps:\n
1.  Go to {self.base_url}\n
2. View/Update your profile: {self.base_url}/userprofile.html\n3. When FBP Pool is open you can make/update your picks:  {self.base_url}/getpicksheet.html\n\n
3. When FBP Pool is open you can make/update your picks:  {self.base_url}/getpicksheet.html\n\n
Questions? Contact us at {self.support_email}.\n\n
Best regards,\n
The FBP Team
        """
        
        return subject, html_content, text_content
    
    @tracer.capture_method
    def _send_ses_email(self, recipient: str, subject: str, html_content: str, 
                       text_content: str, email_type: str, reply_to: Optional[str] = None,
                       tags: Optional[Dict[str, str]] = None) -> str:
        """Send email via SES"""
        
        send_args = {
            'Source': self.default_sender,
            'Destination': {'ToAddresses': [recipient]},
            'Message': {
                'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                'Body': {
                    'Html': {'Data': html_content, 'Charset': 'UTF-8'},
                    'Text': {'Data': text_content, 'Charset': 'UTF-8'}
                }
            }
        }
        
        if reply_to:
            send_args['ReplyToAddresses'] = [reply_to]
        if tags:
            send_args['Tags'] = [{'Name': k, 'Value': v} for k, v in tags.items()]
        
        response = self.ses_client.send_email(**send_args)
        message_id = response['MessageId']
        
        logger.info("Email sent successfully", extra={
            "message_id": message_id,
            "recipient": recipient,
            "email_type": email_type
        })
        
        metrics.add_metric(name="EmailsSent", unit=MetricUnit.Count, value=1)
        metrics.add_metadata(key="email_type", value=email_type)
        
        return message_id

# Initialize service
email_service = EmailService()

@logger.inject_lambda_context
@tracer.capture_lambda_handler  
@metrics.log_metrics
def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Lambda handler - receives event and sends email"""
    
    try:
        # Validate required fields
        recipient = event.get('recipient')
        email_type = event.get('email_type')
        
        if not recipient or not isinstance(recipient, str):
            raise ValueError("Valid recipient email is required")
        if not email_type or not isinstance(email_type, str):
            raise ValueError("Valid email_type is required")
        
        # Send email using the event data
        result = email_service.send_email(
            email_type=email_type,
            recipient=recipient,
            data=event.get('data', {}),
            reply_to=event.get('reply_to'),
            tags=event.get('tags')
        )
        
        # Return the result as a dict for your Lambda chain
        return asdict(result)
        
    except Exception as e:
        logger.error("Lambda handler error", extra={"error": str(e)})
        return {
            'success': False,
            'error': str(e)
        }
