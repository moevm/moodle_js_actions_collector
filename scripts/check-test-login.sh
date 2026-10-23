#!/usr/bin/env bash
# Check the exact password supplied to the test service, without printing it.
set -euo pipefail
cd -- "$(dirname -- "$0")/.."
docker compose --profile test run --rm --no-deps -T --pull never --entrypoint node tests \
  -e 'const p=process.env.MOODLE_STUDENT_PASSWORD; if(!p) process.exit(2); process.stdout.write(p)' |
docker compose exec -T --user www-data moodle php -r '
define("CLI_SCRIPT", true);
require("/var/www/html/config.php");
$password = stream_get_contents(STDIN);
if ($password === "") { fwrite(STDERR, "Test password is empty.\n"); exit(2); }
$user = $DB->get_record("user", ["username" => "student", "mnethostid" => $CFG->mnet_localhost_id, "deleted" => 0]);
if (!$user) { echo "Student account: NOT FOUND\n"; exit(2); }
echo "Student account: found; auth=", $user->auth, "; suspended=", (int)$user->suspended, "; confirmed=", (int)$user->confirmed, "\n";
if ($user->auth !== "manual") { echo "Expected manual authentication; check account settings.\n"; exit(2); }
$matches = validate_internal_user_password($user, $password);
echo "Test password matches stored account: ", ($matches ? "YES" : "NO"), "\n";
exit($matches ? 0 : 1);
'
