# Keep these three images on the same farmOS release, preferably pinned by digest.
ARG FARMOS_BASE_IMAGE=ghcr.io/wotnak/farmos:4
ARG FARMOS_BUILD_IMAGE=ghcr.io/wotnak/farmos:4-dev-runtime
ARG FARMOS_RUNTIME_IMAGE=ghcr.io/wotnak/farmos:4-runtime

FROM ${FARMOS_BASE_IMAGE} AS production

# Use development tools to install modules before copying into the production runtime.
FROM ${FARMOS_BUILD_IMAGE} AS prepare
USER 0:0
ENV COMPOSER_ALLOW_SUPERUSER=1 XDEBUG_MODE=off
WORKDIR /opt/farmos
RUN rm -rf /opt/farmos && mkdir -p /opt/farmos
COPY --from=production /opt/farmos/ /opt/farmos/
RUN chmod -R u+w /opt/farmos

FROM prepare AS build
COPY dependencies/composer.json /tmp/modules.json
# Extend the selected base project, then resolve its latest compatible dependencies.
RUN php -r '\
    $project = json_decode(file_get_contents("composer.json"), true, 512, JSON_THROW_ON_ERROR); \
    $modules = json_decode(file_get_contents("/tmp/modules.json"), true, 512, JSON_THROW_ON_ERROR); \
    $project["require"] = array_replace($project["require"], $modules["require"]); \
    file_put_contents("composer.json", json_encode($project, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR) . "\n");' \
    && composer update --no-audit --no-dev --with-all-dependencies --no-interaction --no-progress --prefer-dist --optimize-autoloader \
    && composer check-platform-reqs --no-dev
# Composer scaffolding must not replace the image's immutable deployment config.
COPY --from=production /opt/farmos/web/sites/default/settings.php /opt/farmos/web/sites/default/settings.php
COPY --from=production /opt/farmos/web/sites/default/services.yml /opt/farmos/web/sites/default/services.yml
RUN chmod -R a-w /opt/farmos \
    && chmod 0755 /opt/farmos/web/sites/default/files \
    && chmod 0700 /opt/farmos/private_files /opt/farmos/private_files/files /opt/farmos/private_files/keys

# Use the production runtime without copying development tools or a second app layer.
FROM ${FARMOS_RUNTIME_IMAGE} AS final
USER 0:0
COPY --from=build --chown=65532:65532 /opt/farmos/ /opt/farmos/
COPY --from=production /usr/bin/farmos-init /usr/bin/farmos-server /usr/bin/
ENV DRUPAL_ROOT=/opt/farmos
WORKDIR /opt/farmos
# Check the actual production PHP extensions, without shipping Composer.
RUN --mount=from=prepare,source=/usr/share/composer/composer.phar,target=/tmp/composer.phar,readonly \
    COMPOSER_ALLOW_SUPERUSER=1 /usr/bin/php /tmp/composer.phar check-platform-reqs --no-dev
USER 65532:65532
ENTRYPOINT ["/usr/bin/farmos-server"]
LABEL org.opencontainers.image.description="farmOS production deployment with contrib modules"
