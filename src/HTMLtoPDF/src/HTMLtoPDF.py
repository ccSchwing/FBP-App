import json
import boto3
import os
import tempfile
from weasyprint import HTML

s3_client = boto3.client('s3')
BUCKET_NAME = os.environ.get('S3BucketName', 'my-fbp.com')
CLOUDFRONT_DOMAIN = os.environ.get('CloudFrontDomain')
PDF_DIR="pdfs"

def lambda_handler(event, context):
    # Get HTML content from the event body
    body = json.loads(event.get('body', '{}'))
    html_content = body.get('html', '<h1>Sorry, Dave, I\'m afraid I can\'t do that.</h1>')
    output_key = body.get('filename', f'output.pdf')
    destination= f'{PDF_DIR}/{output_key}' 

    # Write PDF to /tmp (Lambda's writable directory)
    tmp_pdf_path = f'/tmp/{output_key}'


    # Convert HTML to PDF using WeasyPrint
    HTML(string=html_content).write_pdf(tmp_pdf_path)

    # Upload PDF to S3
    s3_client.upload_file(
        tmp_pdf_path,
        BUCKET_NAME,
        Key=destination,
        ExtraArgs={'ContentType': 'application/pdf'}
    )

    download_url = f'https://{CLOUDFRONT_DOMAIN}/{destination}'

    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'PDF generated successfully!',
            'download_url': download_url,
            's3_key': destination
        })
    }
