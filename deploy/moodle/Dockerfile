FROM alpine:3.22 AS source
RUN apk add --no-cache git
RUN git clone --depth 1 --branch v5.0.2 https://github.com/moodle/moodle.git /moodle \
    && git -C /moodle rev-parse HEAD > /moodle/SOURCE_COMMIT \
    && rm -rf /moodle/.git
FROM php:8.3-apache-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      libicu-dev libzip-dev libpng-dev libjpeg62-turbo-dev libfreetype6-dev libxml2-dev curl util-linux \
    && docker-php-ext-configure gd --with-freetype --with-jpeg \
    && docker-php-ext-install -j2 intl mysqli pdo_mysql zip gd soap exif opcache \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /var/www/html
COPY --from=source --chown=www-data:www-data /moodle/ ./
COPY deploy/moodle/config.php ./config.php
COPY moodle/local/actioncollector/ ./local/actioncollector/
COPY stat_tracker/collector.js ./local/actioncollector/collector.js
COPY deploy/moodle/health.php ./health.php
COPY deploy/moodle/php.ini /usr/local/etc/php/conf.d/moodle.ini
COPY deploy/moodle/seed.php deploy/moodle/entrypoint.sh deploy/moodle/database-state.php /opt/moodle/
RUN chmod +x /opt/moodle/entrypoint.sh \
    && mkdir -p /var/www/moodledata \
    && chown -R www-data:www-data /var/www/html/local/actioncollector /var/www/moodledata \
    && php -r 'define("MOODLE_INTERNAL", true); define("MATURITY_STABLE", 200); require "version.php"; if ($release !== "5.0.2 (Build: 20250811)") {fwrite(STDERR, "Unexpected Moodle release\n"); exit(1);}' \
    && php -r 'foreach (["curl", "mbstring", "sodium", "intl", "mysqli", "pdo_mysql", "zip", "gd", "dom", "xmlreader"] as $ext) { if (!extension_loaded($ext)) {fwrite(STDERR, "Missing extension: $ext\n"); exit(1);} }' \
    && php -l config.php && php -l health.php
RUN find /opt/moodle /var/www/html/local/actioncollector -name '*.php' -print0 | xargs -0 -n1 php -l
ENTRYPOINT ["/opt/moodle/entrypoint.sh"]
CMD ["apache2-foreground"]
