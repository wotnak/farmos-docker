FROM bitnami/minideb as base

ARG UID=1000
ARG GID=1000

COPY --from=composer:2 /usr/bin/composer /usr/local/bin/

RUN set -eux; \
  install_packages apt-transport-https ca-certificates curl patch postgresql-client; \
  curl -sSL https://packages.sury.org/php/README.txt | bash -x; \
  # Install php.
  install_packages \
    php8.1-fpm \
    php8.1-apcu \
    php8.1-bcmath \
    php8.1-curl \
    php8.1-dom \
    php8.1-gd \
    php8.1-mbstring \
    php8.1-opcache \
    php8.1-pdo-mysql \
    php8.1-pdo-pgsql \
    php8.1-simplexml \
    php8.1-uploadprogress \
    php8.1-xmlwriter \
    php8.1-zip; \
  mkdir -p /run/php; chown -R ${UID}:${GID} /run/php; \
  # Build and install the GEOS PHP extension.
  # See https://git.osgeo.org/gitea/geos/php-geos
  install_packages git unzip libgeos-dev php8.1-dev make; \
  git clone https://git.osgeo.org/gitea/geos/php-geos.git; \
  ( \
    cd php-geos; \
    # Checkout latest commit with PHP 8 support.
    git checkout e77d5a16abbf89a59d947d1fe49381a944762c9d; \
    ./autogen.sh; \
    ./configure; \
    make; \
    make install; \
  ); \
  rm -r php-geos; \
  echo "extension=geos.so" > /etc/php/8.1/cli/conf.d/geos.ini; \
  echo "extension=geos.so" > /etc/php/8.1/fpm/conf.d/geos.ini; \
  apt-get remove -y php8.1-dev make; \
  apt-get autoremove -y; \
  # set recommended PHP.ini settings
  # see https://secure.php.net/manual/en/opcache.installation.php
  { \
    echo 'opcache.memory_consumption=128'; \
    echo 'opcache.interned_strings_buffer=8'; \
    echo 'opcache.max_accelerated_files=4000'; \
    echo 'opcache.revalidate_freq=60'; \
    echo 'opcache.fast_shutdown=1'; \
  } | tee /etc/php/8.1/cli/conf.d/opcache-recommended.ini > /etc/php/8.1/fpm/conf.d/opcache-recommended.ini; \
  # Set recommended realpath_cache settings.
  # See https://www.drupal.org/docs/7/managing-site-performance/tuning-phpini-for-drupal
  { \
    echo 'realpath_cache_size=4096K'; \
    echo 'realpath_cache_ttl=3600'; \
  } | tee /etc/php/8.1/cli/conf.d/realpath_cache-recommended.ini > /etc/php/8.1/fpm/conf.d/realpath_cache-recommended.ini; \
  # Set recommended PHP settings for farmOS.
  # See https://farmos.org/hosting/installing/#requirements
  { \
    echo 'memory_limit=256M'; \
    echo 'max_execution_time=240'; \
    echo 'max_input_time=240'; \
    echo 'max_input_vars=5000'; \
    echo 'post_max_size=100M'; \
    echo 'upload_max_filesize=100M'; \
    echo 'expose_php=off'; \
  } | tee /etc/php/8.1/cli/conf.d/farmOS-recommended.ini > /etc/php/8.1/fpm/conf.d/farmOS-recommended.ini; \
  # Make env variables available through $_ENV global.
  { \
    echo 'variables_order=EGPCS'; \
  } | tee /etc/php/8.1/cli/conf.d/env.ini > /etc/php/8.1/fpm/conf.d/env.ini; \
  { \
    echo '[www]'; \
    echo 'clear_env = no'; \
  } > /etc/php/8.1/fpm/pool.d/zz-env.conf; \
  # Disable memory limit for php cli.
  { \
    echo 'memory_limit=-1'; \
  } | tee /etc/php/8.1/cli/conf.d/memory_limit.ini; \
  # Install apache.
  install_packages apache2 libapache2-mod-fcgid; \
  a2enmod alias expires headers proxy proxy_fcgi proxy_http rewrite; \
  a2enconf php8.1-fpm; \
  mkdir -p /var/run/apache2; \
  chown -R ${UID}:${GID} /var/run/apache2 /var/lib/apache2/fcgid /var/www; \
  { \
    echo 'ServerTokens Prod'; \
    echo 'ServerSignature Off'; \
    echo 'ServerName \${FARMOS_DOMAIN}'; \
    echo '<VirtualHost *:80>'; \
    echo '  DocumentRoot /var/www/farmos/web'; \
    echo '  RewriteEngine On'; \
    echo '  <Directory /var/www/farmos>'; \
    echo '    Options -Indexes +FollowSymLinks -MultiViews'; \
    echo '    AllowOverride All'; \
    echo '    Require all granted'; \
    echo '  </Directory>'; \
    echo '  <IfModule mod_expires.c>'; \
    echo '    ExpiresActive On'; \
    echo '    ExpiresByType text/css "access plus 1 year"'; \
    echo '    ExpiresByType text/javascript "access plus 1 year"'; \
    echo '    ExpiresByType application/* "access plus 1 year"'; \
    echo '    ExpiresByType font/* "access plus 1 year"'; \
    echo '    ExpiresByType image/* "access plus 1 year"'; \
    echo '    ExpiresByType video/* "access plus 1 year"'; \
    echo '  </IfModule>'; \
    echo '</VirtualHost>'; \
  } > /etc/apache2/sites-available/000-default.conf; \
  ln -sfT /dev/stderr "/var/log/apache2/error.log"; \
  ln -sfT /dev/stdout "/var/log/apache2/access.log"; \
  ln -sfT /dev/stdout "/var/log/apache2/other_vhosts_access.log"; \
  usermod -u $UID www-data; groupmod -g $GID www-data; chmod -R 775 /var/www

FROM base

ARG UID=1000
ARG GID=1000

WORKDIR /var/www/farmos
RUN mkdir -p web/sites/default; chown -R $UID:$GID /var/www/farmos /var/log

# Switch to use a non-root user.
USER $UID:$GID

COPY --chown=$UID:$GID ./docker-entrypoint /
COPY --chown=$UID:$GID ./composer.json .
COPY --chown=$UID:$GID ./composer.lock .
COPY --chown=$UID:$GID ./settings.php web/sites/default/

RUN composer install --no-cache --no-dev

ENTRYPOINT ["/docker-entrypoint"]
