async function generatePDF(pageUrl, filename) {
    // Load the page in a hidden iframe, grab its HTML
    const iframe = document.createElement('iframe');
    iframe.style.display = 'none';
    document.body.appendChild(iframe);
    iframe.src = pageUrl;
    
    await new Promise(resolve => iframe.onload = resolve);
    const html = iframe.contentDocument.documentElement.outerHTML;
    document.body.removeChild(iframe);

    const response = await fetch(`${API_BASE_URL}/html-to-pdf`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ html, filename })
    });
    const data = await response.json();
    window.open(data.download_url, '_blank');
}
