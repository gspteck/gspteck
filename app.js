const express = require('express');
const path = require('path');
const fs = require('fs');

const app = express();
const port = process.env.PORT || 8080;

// Middleware
app.use(express.static('public'));
app.use(express.json({ limit: '100kb' }));

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/index.html"));
});

app.get('/policy', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/policy.html"));
});

app.get('/delete-account', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/delete-account.html"));
});

// Account deletion request endpoint
app.post('/api/request-deletion', async (req, res) => {
  try {
    const { email, username, product, reason, details, requestedAt } = req.body || {};

    // Basic validation
    if (!email || typeof email !== 'string' || !email.includes('@')) {
      return res.status(400).json({ message: 'A valid email address is required.' });
    }
    if (!product || typeof product !== 'string') {
      return res.status(400).json({ message: 'Please specify which product or service this request is for.' });
    }

    const record = {
      email: email.trim(),
      username: username ? String(username).trim() : null,
      product: product.trim(),
      reason: reason ? String(reason).trim() : null,
      details: details ? String(details).trim() : null,
      requestedAt: requestedAt || new Date().toISOString(),
      ip: req.ip || req.headers['x-forwarded-for'] || 'unknown',
      userAgent: req.headers['user-agent'] || 'unknown',
    };

    // Log to console (always useful)
    console.log('[ACCOUNT DELETION REQUEST]', JSON.stringify(record, null, 2));

    // Persist to a local log file (best-effort, non-blocking for the user)
    const logLine = JSON.stringify(record) + '\n';
    const logPath = path.join(__dirname, 'deletion-requests.log');

    fs.appendFile(logPath, logLine, (err) => {
      if (err) {
        console.error('Failed to write deletion request to log file:', err);
      }
    });

    // Success response
    res.status(200).json({
      message: 'Request received. We will process your account deletion request.',
    });
  } catch (error) {
    console.error('Error processing deletion request:', error);
    res.status(500).json({
      message: 'An internal error occurred. Please email gspteck@gmail.com directly.',
    });
  }
});

app.listen(port, () => {
  console.log("Server started at http://localhost:" + port);
});
