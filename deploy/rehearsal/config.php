<?php
// Disposable manual-install rehearsal. This file is never used by the main site.
unset($CFG);
global $CFG;
$CFG = new stdClass();
$CFG->dbtype = 'mariadb';
$CFG->dblibrary = 'native';
$CFG->dbhost = 'mariadb';
$CFG->dbname = 'moodle';
$CFG->dbuser = 'moodle';
$CFG->dbpass = getenv('MOODLE_DB_PASSWORD');
$CFG->prefix = 'mdl_';
$CFG->dboptions = ['dbpersist' => false, 'dbport' => 3306, 'dbsocket' => '', 'dbcollation' => 'utf8mb4_unicode_ci'];
$CFG->wwwroot = getenv('MOODLE_URL');
$CFG->dataroot = '/var/www/moodledata';
$CFG->admin = 'admin';
$CFG->directorypermissions = 02770;
// Cookies ignore TCP ports: a distinct name prevents collisions with the lab.
$CFG->sessioncookie = 'Manual' . getenv('REHEARSAL_ID');
$CFG->noemailever = true;
$CFG->timezone = 'Europe/Moscow';
$CFG->noreplyaddress = 'noreply@example.com';
$CFG->debugdisplay = false;
require_once(__DIR__ . '/lib/setup.php');
