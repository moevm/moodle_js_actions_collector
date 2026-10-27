#!/usr/bin/env bash
set -euo pipefail
cd /var/www/html

php -r 'define("MOODLE_INTERNAL", true); define("MATURITY_STABLE", 200); require "version.php"; if ($release !== "5.0.2 (Build: 20250811)") {fwrite(STDERR, "Use the project Moodle 5.0.2 image for this rehearsal.\n"); exit(1);}'
# The lab image contains our plugin. Remove it only in this disposable container,
# before installing a new, empty database. Do not run the lab entrypoint/seed.
rm -rf -- /var/www/html/local/actioncollector
mkdir -p /var/www/moodledata
chown www-data:www-data /var/www/moodledata
runuser -u www-data -- php admin/cli/install_database.php \
  --agree-license --lang=en \
  --adminuser=admin --adminpass="$MOODLE_ADMIN_PASSWORD" \
  --adminemail=manual.admin@example.com \
  --fullname="Manual Moodle Rehearsal" --shortname="Manual Rehearsal"
touch /var/www/moodledata/.actions-ready

# Question-bank transfers and other ad-hoc tasks need cron on a fresh site too.
(while true; do
  runuser -u www-data -- php admin/cli/cron.php || echo "Manual Moodle cron failed" >&2
  sleep 60
done) &
exec docker-php-entrypoint apache2-foreground
