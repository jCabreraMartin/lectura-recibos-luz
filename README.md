# Optimizador de factura electrica

Primer nucleo independiente de la comercializadora. Convierte una factura PDF en
un JSON comun que despues podra alimentar comparaciones de tarifas, informes y
alertas.

## Alcance inicial

1. Extraer texto de un PDF digital.
2. Detectar fechas, consumo total, consumos punta/llano/valle, potencia y total.
3. Conservar advertencias y el texto de origen para poder auditar cada dato.
4. No almacenar credenciales ni enviar facturas fuera del equipo.

## Instalacion y uso

```powershell
python -m pip install .
lectura-recibos-luz factura.pdf --output factura.json
```

El lector no presupone Iberdrola, Endesa ni otra compania. Los adaptadores de
comercializadora se anadiran solo para mejorar campos que no puedan reconocerse
con las reglas comunes.

## Privacidad

Las facturas contienen datos personales. El procesamiento es local y los JSON
generados deben mantenerse fuera de repositorios publicos.

## Estado de la primera version

Extrae actualmente:

- comercializadora reconocida;
- periodo de facturacion y numero de dias;
- consumo total y por periodos punta, llano y valle;
- potencia contratada punta y valle;
- importe de energia, servicios, impuesto electrico, contador y factura;
- servicios adicionales detectables por nombre;
- advertencias para campos ausentes o PDF que necesite OCR.

Las reglas comunes se prueban con datos sinteticos. Las facturas reales se usan
solo de manera local para validar el resultado y nunca se incluyen en Git.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

