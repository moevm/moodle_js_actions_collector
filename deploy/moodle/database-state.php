<?php
// Do not bootstrap Moodle before the initial database installation.
$pdo = new PDO('mysql:host=mariadb;dbname=moodle;charset=utf8mb4', 'moodle', getenv('MOODLE_DB_PASSWORD'), [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
$count = $pdo->query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'moodle'")->fetchColumn();
if ((int)$count === 0) { echo "empty"; exit; }
try {
    $version = $pdo->query("SELECT value FROM mdl_config WHERE name = 'version'")->fetchColumn();
} catch (PDOException $e) {
    fwrite(STDERR, "Incomplete Moodle installation. Inspect logs; use new volumes for a fresh install.\n");
    exit(1);
}
if (!$version) { fwrite(STDERR, "Moodle database has no version; installation is incomplete.\n"); exit(1); }
echo "installed";
