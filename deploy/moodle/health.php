<?php
// Startup readiness without changing login state or redirect targets.
header('Content-Type: text/plain');
$file = '/var/www/moodledata/.actions-ready';
if (!is_file($file)) { http_response_code(503); echo 'Starting'; exit; }
echo 'Ready';
