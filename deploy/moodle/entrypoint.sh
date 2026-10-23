#!/usr/bin/env bash
set -euo pipefail
cd /var/www/html
mkdir -p /var/www/moodledata
chown www-data:www-data /var/www/moodledata
rm -f /var/www/moodledata/.actions-ready
state="$(php /opt/moodle/database-state.php)"
if [ "$state" = empty ]; then
  echo "Installing Moodle 5.0.2..."
  runuser -u www-data -- php admin/cli/install_database.php \
    --agree-license --lang=en \
    --adminuser="$MOODLE_ADMIN_USER" --adminpass="$MOODLE_ADMIN_PASSWORD" \
    --adminemail="$MOODLE_ADMIN_EMAIL" \
    --fullname="Moodle Actions Lab" --shortname="Actions Lab"
else
  runuser -u www-data -- php admin/cli/upgrade.php --non-interactive
fi
runuser -u www-data -- php /opt/moodle/seed.php
echo "Moodle ready at $MOODLE_URL"
# Moodle needs cron for background tasks; supervise it alongside Apache.
(while true; do
  runuser -u www-data -- php admin/cli/cron.php || echo "Moodle cron failed" >&2
  sleep 60
done) &
exec docker-php-entrypoint "$@"
