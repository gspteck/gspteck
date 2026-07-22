const express = require('express');
const path = require('path');

const app = express();
const port = process.env.PORT || 8080;

// Serve static files from the public directory
app.use(express.static('public'));

app.get('/', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/index.html"));
});

app.get('/policy', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/policy.html"));
});

app.get('/delete-account', (req, res) => {
  res.sendFile(path.join(__dirname, "/public/delete-account.html"));
});

app.listen(port, () => {
  console.log("Server started at http://localhost:" + port);
});
