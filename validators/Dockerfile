# Validators for the demo: KoSIT validator (EN 16931 CII rules) and Mustang CLI (Factur-X + PDF/A).
# Build: docker build -t facturx-validators:1 validators/
FROM eclipse-temurin:21-jre

RUN apt-get update \
 && apt-get install -y --no-install-recommends unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt

# Official GitHub releases, pinned by sha256 (checked by Docker at download time).
ADD --checksum=sha256:42d7868cb68264874a7b8cab4c3587b03b23ccc7cd72373da917f66758bb9736 \
    https://github.com/ZUGFeRD/mustangproject/releases/download/core-2.26.0/Mustang-CLI-2.26.0.jar \
    /opt/mustang/Mustang-CLI.jar
ADD --checksum=sha256:799e64befca97d4080e03608c80b85dd5a5ecc5f4ae4f35d1116ec2855b9a7c9 \
    https://github.com/itplr-kosit/validator/releases/download/v1.6.3/validator-1.6.3-standalone.jar \
    /opt/kosit/validator.jar
ADD --checksum=sha256:e5f3235824b6b38454b1d54cf3f14e01efb5b33971fbefc4e64997d0ef619e89 \
    https://github.com/ConnectingEurope/eInvoicing-EN16931/releases/download/validation-1.3.17/en16931-cii-1.3.17.zip \
    /tmp/en16931-cii.zip

RUN mkdir -p /opt/kosit/repo \
 && unzip -q -j /tmp/en16931-cii.zip xslt/EN16931-CII-validation.xslt -d /opt/kosit/repo \
 && rm /tmp/en16931-cii.zip

# Our scenario (EN 16931 CII only), report stylesheet and Factur-X XSDs.
COPY kosit/ /opt/kosit/repo/
