# Validators

Docker image with the reference validators (Java 21):

- Mustang CLI 2.26.0 (Factur-X XML rules, French BR-FR rules, PDF/A check)
- KoSIT validator 1.6.3 with a custom scenario: Factur-X EN 16931 XSD + CEN EN 16931 CII schematron 1.3.17
  (not the XRechnung configuration: its German BR-DE rules would reject French invoices)

Download checksums are pinned in the Dockerfile. Build once:

```bash
docker build -t facturx-validators:1 validators/
```

`kosit/xsd/` holds the Factur-X EN 16931 XML schemas, copied from the `factur-x` Python package (BSD license, Akretion / FNFE-MPE).
