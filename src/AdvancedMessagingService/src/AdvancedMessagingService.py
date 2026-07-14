import json
from mailbox import Message
import os
import boto3
from botocore import response
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from typing import Dict, Any, Optional
from enum import Enum
from dataclasses import dataclass, asdict
from botocore.exceptions import ClientError
from aws_lambda_powertools import Logger, Tracer, Metrics
from aws_lambda_powertools.metrics import MetricUnit
from fbplib.fbpLog import fbpLog
from fbplib.getCurrentWeek import getCurrentWeek

logger = Logger()
tracer = Tracer()
metrics = Metrics()


class MessageType(Enum):
    WELCOME = "welcome"
    REMINDER = "reminder"
    PICKSHEET = "picksheet"
    GRIDSHEET = "gridsheet"
    WEEKLYWINNER = "weeklywinner"


@dataclass
class MessagingResponse:
    success: bool
    channel: Optional[str] = None
    message_type: Optional[str] = None
    recipient: Optional[str] = None
    message_id: Optional[str] = None
    error: Optional[str] = None


def _is_opted_in(value: Any) -> bool:
    """Normalize DynamoDB opt-in values stored as bool, number, or string."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y", "on"}
    return False


# ---------------------------------------------------------------------------
# Email Service
# ---------------------------------------------------------------------------

class EmailService:
    """Sends email via SES."""

    def __init__(self):
        self.ses_client = boto3.client('ses')
        self.default_sender = os.environ.get('FROM_EMAIL', 'fbpadmin@my-fbp.com')
        self.company_name = os.environ.get('COMPANY_NAME', 'FBP')
        self.base_url = os.environ.get('BASE_URL', 'https://my-fbp.com')
        self.support_email = os.environ.get('SUPPORT_EMAIL', 'fbpadmin@my-fbp.com')

    @tracer.capture_method
    def send(self, message_type: str, recipient: Optional[str],
             data: Dict[str, Any], reply_to: Optional[str] = None,
             tags: Optional[Dict[str, str]] = None) -> MessagingResponse:

        try:
            msg_enum = MessageType(message_type)
            content_generator = self._get_content_generator(msg_enum)

            match msg_enum:
                case MessageType.WELCOME:
                    if not recipient or '@' not in recipient:
                        raise ValueError("Valid recipient email is required for welcome emails")
                    data['user_name'] = self._get_user_first_name(recipient) or recipient
                    msg_id = self._send_one(recipient, content_generator, data, reply_to, tags, message_type)
                    return MessagingResponse(success=True, channel="email", message_type=message_type,
                                            recipient=recipient, message_id=msg_id)

                case MessageType.REMINDER:
                    users = self._get_bulk_users('emailReminders')
                    if not users:
                        logger.info("No reminder users found")
                    for user in users:
                        user_data = {**data, "user_name": user.get("firstName") or user["email"]}
                        self._send_one(user["email"], content_generator, user_data, reply_to, tags, message_type)
                    return MessagingResponse(success=True, channel="email", message_type=message_type,
                                            recipient=recipient, message_id=f"bulk:{len(users)}")

                case MessageType.PICKSHEET:
                    users = self._get_bulk_users('emailPickSheet')
                    if not users:
                        logger.info("No picksheet users found")
                    for user in users:
                        user_data = {**data, "user_name": user.get("firstName") or user["email"]}
                        self._send_one(user["email"], content_generator, user_data, reply_to, tags, message_type)
                    return MessagingResponse(success=True, channel="email", message_type=message_type,
                                            recipient=recipient, message_id=f"bulk:{len(users)}")

                case MessageType.GRIDSHEET:
                    users = self._get_bulk_users('emailGridSheet')
                    if not users:
                        logger.info("No gridsheet users found")
                    for user in users:
                        user_data = {**data, "user_name": user.get("firstName") or user["email"]}
                        self._send_one(user["email"], content_generator, user_data, reply_to, tags, message_type)
                    return MessagingResponse(success=True, channel="email", message_type=message_type,
                                            recipient=recipient, message_id=f"bulk:{len(users)}")

                case MessageType.WEEKLYWINNER:
                    winner_email=self._get_winner()
                    winner_display_name = self._get_user_display_name(winner_email) if winner_email else None
                    data["display_name"] = winner_display_name
                    if winner_email:
                        fbpLog(winner_email, "WeeklyWinner", "Weekly Winner Announcement Sent", "INFO")
                    else:
                        logger.info("No weekly winner found")
                    users=self._get_all_users()
                    if not users:
                        logger.info("No users found for weekly winner announcement")
                    for user in users:
                        self._send_one(user["email"], content_generator, data, reply_to, tags, message_type)
                    return MessagingResponse(success=True, channel="email", message_type=message_type,
                                            recipient=recipient, message_id=f"bulk:{len(users)}")
                case _:
                    raise ValueError(f"Unsupported message type: {message_type}")

        except Exception as e:
            logger.error("Failed to send email", extra={"error": str(e), "message_type": message_type})
            return MessagingResponse(success=False, channel="email", message_type=message_type,
                                     recipient=recipient, error=str(e))

    def _get_user_first_name(self, email: str) -> Optional[str]:
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name:
            return None
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            response = table.get_item(Key={'email': email}, ProjectionExpression='firstName')
            return response.get('Item', {}).get('firstName')
        except Exception as e:
            logger.warning("Failed to get user firstName", extra={"error": str(e), "email": email})
            return None

    def _get_user_display_name(self, email: str) -> Optional[str]:
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name:
            return None
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            response = table.get_item(Key={'email': email}, ProjectionExpression='displayName')
            return response.get('Item', {}).get('displayName')
        except Exception as e:
            logger.warning("Failed to get user displayName", extra={"error": str(e), "email": email})
            return None
        
    
    def _get_winner(self) -> Optional[str]:
        """Get the weekly winner's name for the current week."""
        current_week = getCurrentWeek()
        winners_table_name = os.environ.get('FBPWeeklyResults2025TableName')
        if not winners_table_name:
            logger.info("FBPWeeklyResults2025TableName not set; cannot get winner")
            return None
        try:
            table = boto3.resource('dynamodb').Table(winners_table_name)
            ##
            # get the winner where week = current_week and winner is true
            ##
            response = table.query(
                IndexName=os.environ.get('FBPWeeklyResults2025WeekIndexName', 'WeekIndex'),
                KeyConditionExpression='#wk = :wk',
                FilterExpression='#win = :w',
                ExpressionAttributeNames={'#wk': 'week', '#win': 'winner'},
                ExpressionAttributeValues={':wk': current_week, ':w': True},
                ProjectionExpression='email'
            )
            winner_email = response.get('Items', [{}])[0].get('email')

            return winner_email
        except Exception as e:
            logger.warning("Failed to get weekly winner", extra={"error": str(e), "week": current_week})
            return None

    def _get_all_users(self) -> list:
        """Scan DynamoDB for all users (used for weekly winner announcements)."""
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name:
            logger.info("FBPUSERS_TABLE_NAME not set; no users found")
            return []
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            items = table.scan(ProjectionExpression='email, firstName').get("Items", [])
            return [u for u in items if u.get('email') and u.get('firstName')]
        except Exception as e:
            logger.warning("DynamoDB scan failed", extra={"error": str(e)})
            return []
        

    def _get_bulk_users(self, opt_in_field: str) -> list:
        """Scan DynamoDB for users opted in to the given field."""
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name:
            logger.info("FBPUSERS_TABLE_NAME not set; no bulk recipients")
            return []
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            items = table.scan(
                ProjectionExpression=f'email, firstName, {opt_in_field}'
            ).get("Items", [])
            return [u for u in items if _is_opted_in(u.get(opt_in_field)) 
                    and u.get('email') and u.get('firstName') ]
        except Exception as e:
            logger.warning("DynamoDB scan failed", extra={"error": str(e), "field": opt_in_field})
            return []

    def _send_one(self, recipient: str, content_generator, data: Dict[str, Any],
                  reply_to: Optional[str], tags: Optional[Dict[str, str]], message_type: str) -> str:
        subject, html_content, text_content = content_generator(data)
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
        logger.info("Email sent", extra={"message_id": message_id, "recipient": recipient, "message_type": message_type})
        metrics.add_metric(name="EmailsSent", unit=MetricUnit.Count, value=1)
        metrics.add_metadata(key="message_type", value=message_type)
        return message_id

    def _get_content_generator(self, msg_type: MessageType):
        generators = {
            MessageType.WELCOME: self._welcome_content,
            MessageType.REMINDER: self._reminder_content,
            MessageType.PICKSHEET: self._picksheet_content,
            MessageType.GRIDSHEET: self._gridsheet_content,
            MessageType.WEEKLYWINNER: self._weeklywinner_content,
        }
        generator = generators.get(msg_type)
        if not generator:
            raise ValueError(f"Unsupported email message type: {msg_type.value}")
        return generator

    def _welcome_content(self, data: Dict[str, Any]) -> tuple:
        user_name = data.get('user_name', 'User')
        subject = "Welcome to FBP -- Your Account is Ready"
        html = f"""
        <html><body>
            <h1>Welcome to {self.company_name}, {user_name}!</h1>
            <p>Many thanks for joining {self.company_name}! Your account has been created successfully.</p>
            <p>When you click on the FBP Home link, you'll be taken to the login screen. Enter your email
            and password and you'll be directed to the home page.</p>
            <p>In the unlikely event that you've forgotten your password, you can easily reset it at the login page.</p>
            <ul>
                <li>FBP Home: <a href="{self.base_url}">FBP Home</a></li>
                <li>Membership Payment: <a href="{self.base_url}/makepayment.html">Payment Options</a></li>
                <li>FAQ: <a href="{self.base_url}/faq.html">FAQ</a></li>
            </ul>
            <p>Need help? Contact us at <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body></html>
        """
        text = (f"Hello {user_name} --\n\nWelcome to {self.company_name}! Your account has been successfully created.\n\n"
                f"1. Go to {self.base_url}\n"
                f"2. Make a payment: {self.base_url}/makepayment.html\n"
                f"3. FAQ: {self.base_url}/faq.html\n\n"
                f"Questions? Contact us at {self.support_email}.\n\nBest regards,\nThe {self.company_name} Team")
        return subject, html, text

    def _reminder_content(self, data: Dict[str, Any]) -> tuple:
        user_name = data.get('user_name', 'User')
        subject = f"Reminder from {self.company_name}"
        html = f"""
        <html><body>
            <h1>Reminder from {self.company_name}, {user_name}!</h1>
            <p>You still have time to make your {self.company_name} picks for the week.</p>
            <p>Visit: <a href="{self.base_url}">{self.company_name} Home</a></p>
            <p>Questions? <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body></html>
        """
        text = (f"Hello {user_name} --\n\nYou still have time to make your {self.company_name} picks for the week.\n"
                f"Visit: {self.base_url}\n\nQuestions? {self.support_email}\n\nBest regards,\nThe {self.company_name} Team")
        return subject, html, text

    def _picksheet_content(self, data: Dict[str, Any]) -> tuple:
        user_name = data.get('user_name', 'User')
        subject = f"{self.company_name} Is Open for Picks."
        html = f"""
        <html><body>
            <h1>Hi {user_name} from {self.company_name}!</h1>
            <p>Visit: <a href="{self.base_url}">{self.company_name} Home</a> to make your picks.</p>
            <p>FAQ: <a href="{self.base_url}/faq.html">FAQ</a></p>
            <p>Questions? <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body></html>
        """
        text = (f"Hello {user_name} --\n\n{self.company_name} is open for picks.\n"
                f"Visit: {self.base_url}\nFAQ: {self.base_url}/faq.html\n\n"
                f"Questions? {self.support_email}\n\nBest regards,\nThe {self.company_name} Team")
        return subject, html, text
    def _gridsheet_content(self, data: Dict[str, Any]) -> tuple:
        user_name = data.get('user_name', 'User')
        subject = f"{self.company_name} Grid Sheet is Live!"
        html = f"""
        <html><body>
            <h1>Hi {user_name} from {self.company_name}!</h1>
            <p>The grid sheet is now live for this week.</p>
            <p>Visit: <a href="{self.base_url}">{self.company_name} Home</a> to view the grid sheet.</p>
            <p>FAQ: <a href="{self.base_url}/faq.html">FAQ</a></p>
            <p>Questions? <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body></html>
        """
        text = (f"Hello {user_name} --\n\nThe grid sheet is now live for this week.\n"
                f"Visit: {self.base_url}\nFAQ: {self.base_url}/faq.html\n\n"
                f"Questions? {self.support_email}\n\nBest regards,\nThe {self.company_name} Team")
        return subject, html, text
    def _weeklywinner_content(self, data: Dict[str, Any]) -> tuple:
        display_name = data.get('display_name', 'the winner')
        subject = f"Congratulations to {display_name} -- This Week's {self.company_name} Winner!"
        html = f"""
        <html><body>
            <h1>Congratulations to {display_name}!</h1>
            <p>{display_name} is this week's {self.company_name} winner. Great job!</p>
            <p>Visit: <a href="{self.base_url}">{self.company_name} Home</a> to view the results.</p>
            <p>FAQ: <a href="{self.base_url}/faq.html">FAQ</a></p>
            <p>Questions? <a href="mailto:{self.support_email}"><b>{self.support_email}</b></a></p>
            <p>Best regards,<br>The {self.company_name} Team</p>
        </body></html>
        """
        text = (f"Congratulations to {display_name}!\n\n"
                f"{display_name} is this week's {self.company_name} winner. Great job!\n\n"
                f"Visit: {self.base_url}\nFAQ: {self.base_url}/faq.html\n\n"
                f"Questions? {self.support_email}\n\nBest regards,\nThe {self.company_name} Team")
        return subject, html, text


# ---------------------------------------------------------------------------
# SMS Service
# ---------------------------------------------------------------------------

class SMSService:
    """Sends SMS via Twilio."""

    def __init__(self):
        secrets = self._get_secrets()
        self.sms_client = Client(secrets['TWILIO_ACCOUNT_SID'], secrets['TWILIO_AUTH_TOKEN'])
        self.default_sender = secrets['TWILIO_PHONE_NUMBER']
        self.company_name = os.environ.get('COMPANY_NAME', 'FBP')
        self.base_url = os.environ.get('BASE_URL', 'https://my-fbp.com')

    def _get_secrets(self) -> dict:
        client = boto3.client('secretsmanager')
        response = client.get_secret_value(SecretId=os.environ['TWILIO_CREDENTIALS_SECRET_ARN'])
        return json.loads(response['SecretString'])

    @tracer.capture_method
    def send(self, message_type: str, recipient: Optional[str],
             data: Dict[str, Any]) -> MessagingResponse:
        try:
            msg_enum = MessageType(message_type)
            content_generator = self._get_content_generator(msg_enum)

            match msg_enum:
                case MessageType.WELCOME:
                    if not recipient:
                        raise ValueError("Recipient phone number is required for welcome SMS")
                    data['user_name'] = self._get_user_first_name(recipient) or recipient
                    msg_id = self._send_one(recipient, content_generator, data, message_type)
                    return MessagingResponse(success=True, channel="sms", message_type=message_type,
                                            recipient=recipient, message_id=msg_id)

                case MessageType.REMINDER | MessageType.PICKSHEET | MessageType.GRIDSHEET:
                    users = self._get_bulk_users(msg_enum)
                    if not users:
                        logger.info(f"No SMS users found for {message_type}")
                    for user in users:
                        user_data = {**data, "user_name": user.get("firstName") or user["mobile_number"]}
                        self._send_one(user["mobile_number"], content_generator, user_data, message_type)
                    return MessagingResponse(success=True, channel="sms", message_type=message_type,
                                            recipient=recipient, message_id=f"bulk:{len(users)}")

                case _:
                    raise ValueError(f"Unsupported message type: {message_type}")

        except Exception as e:
            logger.error("Failed to send SMS", extra={"error": str(e), "message_type": message_type})
            return MessagingResponse(success=False, channel="sms", message_type=message_type,
                                     recipient=recipient, error=str(e))

    def _get_user_first_name(self, mobile_number: str) -> Optional[str]:
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name:
            return None
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            response = table.scan(
                FilterExpression='mobile_number = :mn',
                ExpressionAttributeValues={':mn': self._normalize_phone(mobile_number)},
                ProjectionExpression='firstName'
            )
            items = response.get('Items', [])
            return items[0].get('firstName') if items else None
        except Exception as e:
            logger.warning("Failed to get user firstName", extra={"error": str(e), "mobile_number": mobile_number})
            return None

    def _get_bulk_users(self, msg_type: MessageType) -> list:
        """Scan DynamoDB for users opted in to SMS for the given message type."""
        opt_in_field_map = {
            MessageType.REMINDER: 'smsReminders',
            MessageType.PICKSHEET: 'smsPickSheet',
            MessageType.GRIDSHEET: 'smsGridSheet',
        }
        opt_in_field = opt_in_field_map.get(msg_type)
        users_table_name = os.environ.get('FBPUSERS_TABLE_NAME')
        if not users_table_name or not opt_in_field:
            logger.info("FBPUSERS_TABLE_NAME not set or no opt-in field; no bulk SMS recipients")
            return []
        try:
            table = boto3.resource('dynamodb').Table(users_table_name)
            items = table.scan(
                ProjectionExpression=f'mobile_number, firstName, {opt_in_field}'
            ).get("Items", [])
            return [u for u in items if _is_opted_in(u.get(opt_in_field)) 
                    and u.get('firstName')and u.get('mobile_number')
                    and not self._is_opted_out(u['mobile_number'])]
        except Exception as e:
            logger.warning("DynamoDB scan failed for SMS", extra={"error": str(e)})
            return []

    def _is_opted_out(self, phone_number: str) -> bool:
        """Check DynamoDB opt-out table (covers /userprofile.html opt-out; Twilio STOP is handled by Twilio)."""
        opt_out_table_name = os.environ.get('TWILIO_OPT_OUT_TABLE_NAME')
        if not opt_out_table_name:
            return False
        try:
            table = boto3.resource('dynamodb').Table(opt_out_table_name)
            response = table.get_item(Key={'phone_number': self._normalize_phone(phone_number)})
            return response.get('Item', {}).get('opted_out', False)
        except ClientError as e:
            logger.warning("Opt-out check failed; defaulting to not opted out",
                           extra={"error": str(e), "phone": phone_number})
            return False

    def _normalize_phone(self, phone: str) -> str:
        digits = ''.join(filter(str.isdigit, phone))
        if len(digits) == 10:
            return f"+1{digits}"
        return f"+{digits}"

    def _send_one(self, recipient: str, content_generator, data: Dict[str, Any], message_type: str) -> str:
        normalized = self._normalize_phone(recipient)
        if self._is_opted_out(normalized):
            logger.info("Skipping opted-out recipient", extra={"recipient": normalized})
            metrics.add_metric(name="OptedOutSMS", unit=MetricUnit.Count, value=1)
            return f"opted-out:{normalized}"

        text_content = content_generator(data)
        message = self.sms_client.messages.create(
            body=text_content,
            from_=self.default_sender,
            to=normalized
        )
        logger.info("SMS sent", extra={"message_sid": message.sid, "recipient": normalized, "message_type": message_type})
        metrics.add_metric(name="SMSSent", unit=MetricUnit.Count, value=1)
        metrics.add_metadata(key="message_type", value=message_type)
        return str(message.sid)

    def _get_content_generator(self, msg_type: MessageType):
        generators = {
            MessageType.WELCOME: self._welcome_content,
            MessageType.REMINDER: self._reminder_content,
            MessageType.PICKSHEET: self._picksheet_content,
            MessageType.GRIDSHEET: self._gridsheet_content,
        }
        generator = generators.get(msg_type)
        if not generator:
            raise ValueError(f"Unsupported SMS message type: {msg_type.value}")
        return generator

    def _welcome_content(self, data: Dict[str, Any]) -> str:
        user_name = data.get('user_name', 'User')
        return (f"Welcome to {self.company_name}!\n"
                f"Hi {user_name}, your account has been created.\n"
                f"Visit {self.base_url} to get started.\n"
                f"FAQ: {self.base_url}/faq.html")

    def _reminder_content(self, data: Dict[str, Any]) -> str:
        user_name = data.get('user_name', 'User')
        return (f"Hi {user_name}, {self.company_name} picks is still open!\n"
                f"Visit {self.base_url}\n"
                f"FAQ: {self.base_url}/faq.html")

    def _picksheet_content(self, data: Dict[str, Any]) -> str:
        user_name = data.get('user_name', 'User')
        return (f"Hi {user_name}, {self.company_name} Pool is open. Make your picks!\n"
                f"Visit {self.base_url}\n"
                f"FAQ: {self.base_url}/faq.html")

    def _gridsheet_content(self, data: Dict[str, Any]) -> str:
        user_name = data.get('user_name', 'User')
        return (f"Hi {user_name}, {self.company_name} is closed for picks. Grid sheet is live!\n"
                f"Visit {self.base_url}\n"
                f"FAQ: {self.base_url}/faq.html")

# ---------------------------------------------------------------------------
# Lambda Handler
# ---------------------------------------------------------------------------

email_service = EmailService()
sms_service = SMSService()

@logger.inject_lambda_context
@tracer.capture_lambda_handler
@metrics.log_metrics
def lambda_handler(event: Dict[str, Any], context) -> Dict[str, Any]:
    try:
        payload = event
        if isinstance(event, dict) and "body" in event:
            body = event.get("body")
            payload = json.loads(body) if isinstance(body, str) else (body or {})

        channel = payload.get('channel', '').lower()
        message_type = payload.get('message_type')
        recipient = payload.get('recipient')

        if not channel or channel not in ('email', 'sms'):
            raise ValueError("'channel' must be 'email' or 'sms'")
        if not message_type or not isinstance(message_type, str):
            raise ValueError("'message_type' is required")

        if channel == 'email':
            result = email_service.send(
                message_type=message_type,
                recipient=recipient,
                data=payload,
                reply_to=payload.get('reply_to'),
                tags=payload.get('tags')
            )
        else:
            result = sms_service.send(
                message_type=message_type,
                recipient=recipient,
                data=payload
            )

        return asdict(result)

    except Exception as e:
        logger.error("Lambda handler error", extra={"error": str(e)})
        fbpLog("fbpadmin@my-fbp.com", "AdvancedMessagingService", str(e), "ERROR")
        return {'success': False, 'error': str(e)}
