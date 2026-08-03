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
    body = json.loads(event.get('body', '{}'))
    url = body.get('url')
    html_content = body.get('html')
    output_key = body.get('filename', 'output.pdf')
    destination = f'{PDF_DIR}/{output_key}'
    tmp_pdf_path = f'/tmp/{output_key}'

    if url:
        HTML(url=url).write_pdf(tmp_pdf_path)
    elif html_content:
        HTML(string=html_content).write_pdf(tmp_pdf_path)
    else:
        return {'statusCode': 400, 'body': json.dumps({'error': 'Provide either url or html'})}

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
