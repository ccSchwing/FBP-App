import { getServiceUrl } from "/js-lib/urlConfig.js";

export async function sendChatBotMessage() {
    const input = document.getElementById('chat-input');
    const question = input.value.trim();
    
    if (!question) return;
    
    addMessage('user', question);
    input.value = '';
    
    try {
        const apiEndpoint = await getServiceUrl("chatbot");

        const response = await fetch(apiEndpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question, sessionId: getSessionId() })
        });
        
        const data = await response.json();
        addMessage('bot', response.ok ? data.answer : 'Sorry, I encountered an error. Please try again.');
    } catch (error) {
        console.error('Error:', error);
        addMessage('bot', 'Sorry, I could not connect to the server.');
    }
}

function addMessage(sender, message) {
    const messagesDiv = document.getElementById('chat-messages');
    const messageDiv = document.createElement('div');
    messageDiv.className = sender;
    messageDiv.textContent = message;
    messagesDiv.appendChild(messageDiv);
    messagesDiv.scrollTop = messagesDiv.scrollHeight;
}

function getSessionId() {
    let sessionId = localStorage.getItem('fbp-chat-session');
    if (!sessionId) {
        sessionId = 'session-' + Date.now();
        localStorage.setItem('fbp-chat-session', sessionId);
    }
    return sessionId;
}
