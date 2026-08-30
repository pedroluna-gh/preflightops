FROM gcr.io/oss-fuzz-base/base-builder-python

COPY . $SRC/preflightops
WORKDIR $SRC/preflightops
COPY .clusterfuzzlite/build.sh $SRC/build.sh
RUN chmod +x $SRC/build.sh

