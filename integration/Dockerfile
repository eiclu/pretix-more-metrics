# pretix with this plugin installed, the same way you would build it in production.
ARG PRETIX_IMAGE=pretix/standalone:stable
FROM ${PRETIX_IMAGE}
USER root
COPY . /tmp/pretix-more-metrics
# --no-build-isolation: build with the setuptools already in the image, no network needed
RUN pip3 install --no-cache-dir --no-build-isolation --no-deps /tmp/pretix-more-metrics && rm -rf /tmp/pretix-more-metrics
USER pretixuser
RUN cd /pretix/src && make production
