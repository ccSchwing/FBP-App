import json
import boto3
from typing import Dict, Any, List, Optional
from enum import Enum
from dataclasses import dataclass
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit

logger = Logger()
tracer = Tracer()
metrics = Metrics()

class EmailType(Enum):
    WELCOME = "welcome"
    PASSWORD_RESET = "password_reset"
    ORDER_CONFIRMATION = "order_confirmation"
    NOTIFICATION = "notification"

@dataclass
class EmailRequest:
    email_type: EmailType
    recipient: str
    data: Dict[str, Any]
    sender_name: Optional[str] = None

class AdvancedEmailService:
    """Advanced email service with multiple email types"""
    
    def __init__(self, ses_client):
        self.ses_client = ses_client
        self.default_sender = "noreply@yourcompany.com"
        self.company_name = "Your Company"
    
    @tracer.capture_method
    def send_email(self, email_request: EmailRequest) -> str:
        """Route email sending based on type"""
        
        email_handlers = {
            EmailType.WELCOME: self._send_welcome_email,
            EmailType.PASSWORD_RESET: self._send_password_reset_email,
            EmailType.ORDER_CONFIRMATION: self._send_order_confirmation_email,
            EmailType.NOTIFICATION: self._send_notification_email
        }
        
        handler = email_handlers.get(email_request.email_type)
        if not handler:
            raise ValueError(f"Unsupported email type: {email_request.email_type}")
        
        return handler(email_request)
    
    def _send_welcome_email(self, request: EmailRequest) -> str:
        """Send welcome email"""
        user_name = request.data.get('user_name', 'User')
        activation_link = request.data.get('activation_link', 'https://yourapp.com/activate')
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 40px; text-align: center; color: white;">
                <h1>Welcome to {self.company_name}! 🎉</h1>
            </div>
            <div style="padding: 30px;">
                <h2>Hi {user_name},</h2>
                <p>We're excited to have you on board! Your journey with us starts now.</p>
                
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3>🚀 Quick Start Guide:</h3>
                    <ul>
                        <li>Activate your account</li>
                        <li>Complete your profile</li>
                        <li>Explore our features</li>
                    </ul>
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{activation_link}" 
                       style="background-color: #28a745; color: white; padding: 15px 30px; 
                              text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Activate Account
                    </a>
                </div>
                
                <p>Need help? Reply to this email or visit our <a href="https://yourapp.com/help">Help Center</a>.</p>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Welcome to {self.company_name}!
        
        Hi {user_name},
        
        We're excited to have you on board! Your journey with us starts now.
        
        Quick Start Guide:
        - Activate your account: {activation_link}
        - Complete your profile
        - Explore our features
        
        Need help? Reply to this email or visit: https://yourapp.com/help
        
        Best regards,
        The {self.company_name} Team
        """
        
        return self._send_ses_email(
            recipient=request.recipient,
            subject=f"Welcome to {self.company_name}, {user_name}! 🎉",
            html_content=html_content,
            text_content=text_content,
            email_type="welcome"
        )
    
    def _send_password_reset_email(self, request: EmailRequest) -> str:
        """Send password reset email"""
        user_name = request.data.get('user_name', 'User')
        reset_link = request.data.get('reset_link')
        expires_in = request.data.get('expires_in', '1 hour')
        
        if not reset_link:
            raise ValueError("reset_link is required for password reset emails")
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #dc3545; padding: 30px; text-align: center; color: white;">
                <h1>🔒 Password Reset Request</h1>
            </div>
            <div style="padding: 30px;">
                <h2>Hi {user_name},</h2>
                <p>We received a request to reset your password. If you didn't make this request, you can safely ignore this email.</p>
                
                <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0;">
                    <strong>⚠️ Security Notice:</strong> This link expires in {expires_in}.
                </div>
                
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{reset_link}" 
                       style="background-color: #dc3545; color: white; padding: 15px 30px; 
                              text-decoration: none; border-radius: 5px; font-weight: bold;">
                        Reset Password
                    </a>
                </div>
                
                <p><small>If the button doesn't work, copy and paste this link: {reset_link}</small></p>
            </div>
        </body>
        </html>
        """
        
        text_content = f"""
        Password Reset Request
        
        Hi {user_name},
        
        We received a request to reset your password. If you didn't make this request, you can safely ignore this email.
        
        Reset your password: {reset_link}
        
        Security Notice: This link expires in {expires_in}.
        
        Best regards,
        The {self.company_name} Team
        """
        
        return self._send_ses_email(
            recipient=request.recipient,
            subject="Reset Your Password",
            html_content=html_content,
            text_content=text_content,
            email_type="password_reset"
        )
    
    def _send_order_confirmation_email(self, request: EmailRequest) -> str:
        """Send order confirmation email"""
        order_id = request.data.get('order_id')
        customer_name = request.data.get('customer_name', 'Customer')
        items = request.data.get('items', [])
        total = request.data.get('total', '0.00')
        tracking_url = request.data.get('tracking_url')
        
        # Generate items HTML
        items_html = ""
        for item in items:
            items_html += f"""
            <tr>
                <td style="padding: 10px; border-bottom: 1px solid #eee;">{item.get('name', 'Item')}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: center;">{item.get('quantity', 1)}</td>
                <td style="padding: 10px; border-bottom: 1px solid #eee; text-align: right;">${item.get('price', '0.00')}</td>
            </tr>
            """
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #28a745; padding: 30px; text-align: center; color: white;">
                <h1>✅ Order Confirmed!</h1>
                <p>Order #{order_id}</p>
            </div>
            <div style="padding: 30px;">
                <h2>Thank you, {customer_name}!</h2>
                <p>Your order has been confirmed and is being processed.</p>
                
                <div style="background-color: #f8f9fa; padding: 20px; border-radius: 8px; margin: 20px 0;">
                    <h3>Order Details:</h3>
                    <table style="width: 100%; border-collapse: collapse;">
                        <thead>
                            <tr style="background-color: #e9ecef;">
                                <th style="padding: 10px; text-align: left;">Item</th>
                                <th style="padding: 10px; text-align: center;">Qty</th>
                                <th style="padding: 10px; text-align: right;">Price</th>
                            </tr>
                        </thead>
                        <tbody>
                            {items_html}
                            <tr style="font-weight: bold; background-color: #e9ecef;">
                                <td style="padding: 15px;" colspan="2">Total:</td>
                                <td style="padding: 15px; text-align: right;">${total}</td>
                            </tr>
                        </tbody>
                    </table>
                </div>
                
                {f'<p><a href="{tracking_url}" style="color: #007bff;">Track your order</a></p>' if tracking_url else ''}
                
                <p>We'll send you another email when your order ships.</p>
            </div>
        </body>
        </html>
        """
        
        return self._send_ses_email(
            recipient=request.recipient,
            subject=f"Order Confirmation #{order_id}",
            html_content=html_content,
            text_content=f"Order #{order_id} confirmed. Total: ${total}",
            email_type="order_confirmation"
        )
    
    def _send_notification_email(self, request: EmailRequest) -> str:
        """Send generic notification email"""
        title = request.data.get('title', 'Notification')
        message = request.data.get('message', '')
        action_url = request.data.get('action_url')
        action_text = request.data.get('action_text', 'View Details')
        
        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #17a2b8; padding: 30px; text-align: center; color: white;">
                <h1>📢 {title}</h1>
            </div>
            <div style="padding: 30px;">
                <p>{message}</p>
                
                {f'''
                <div style="text-align: center; margin: 30px 0;">
                    <a href="{action_url}" 
                       style="background-color: #17a2b8; color: white; padding: 15px 30px; 
                              text-decoration: none; border-radius: 5px; font-weight: bold;">
                        {action_text}
                    </a>
                </div>
                ''' if action_url else ''}
            </div>
        </body>
        </html>
        """
        
        return self._send_ses_email(
            recipient=request.recipient,
            subject=title,
            html_content=html_content,
            text_content=f"{title}\n\n{message}" + (f"\n\n{action_text}: {action_url}" if action_url else ""),
            email_type="notification"
        )
    
    @tracer.capture_method
    def _send_ses_email(self, recipient: str, subject: str, html_content: str, 
                       text_content: str, email_type: str) -> str:
        """Send email via SES"""
        try:
            response = self.ses_client.send_email(
                Source=self.default_sender,
                Destination={'ToAddresses': [recipient]},
                Message={
                    'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                    'Body': {
                        'Html': {'Data': html_content, 'Charset': 'UTF-8'},
                        'Text': {'Data': text_content, 'Charset': 'UTF-8'}
                    }
                }
            )
            
            message_id = response['MessageId']
            
            logger.info("Email sent successfully", extra={
                "message_id": message_id,
                "recipient": recipient,
                "email_type": email_type,
                "subject": subject
            })
            
            metrics.add_metric(name="EmailsSent", unit=MetricUnit.Count, value=1)
            metrics.add_metadata(key="email_type", value=email_type)
            
            return message_id
            
        except ClientError as e:
            logger.error("Failed to send email", extra={
                "error_code": e.response['Error']['Code'],
                "error_message": e.response['Error']['Message'],
                "recipient": recipient,
                "email_type": email_type
            })
            
            metrics.add_metric(name="EmailErrors", unit=MetricUnit.Count, value=1)
            metrics.add_metadata(key="email_type", value=email_type)
            metrics.add_metadata(key="error_code", value=e.response['Error']['Code'])
            
            raise

# Initialize service
email_service = AdvancedEmailService(boto3.client('ses'))

@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    """Advanced Lambda handler for multiple email types"""
    
    try:
        body = json.loads(event.get('body', '{}'))
        
        # Create email request
        email_request = EmailRequest(
            email_type=EmailType(body.get('email_type')),
            recipient=body.get('recipient'),
            data=body.get('data', {}),
            sender_name=body.get('sender_name')
        )
        
        # Send email
        message_id = email_service.send_email(email_request)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': f'{email_request.email_type.value} email sent successfully',
                'message_id': message_id
            })
        }
        
    except ValueError as e:
        logger.error("Invalid request", extra={"error": str(e)})
        return {
            'statusCode': 400,
            'body': json.dumps({'error': str(e)})
        }
    
    except ClientError as e:
        logger.error("SES error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({
                'error': 'Failed to send email',
                'details': e.response['Error']['Message']
            })
        }
    
    except Exception as e:
        logger.error("Unexpected error", extra={"error": str(e)})
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error'})
        }
