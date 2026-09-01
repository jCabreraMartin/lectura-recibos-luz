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

Si un PDF no contiene texto seleccionable, el lector aplica OCR local con
Tesseract. Las imagenes intermedias se crean en una carpeta temporal y se borran
automaticamente.

En Windows, instala previamente el motor OCR y acepta el aviso de permisos:

```powershell
winget install --id tesseract-ocr.tesseract --exact
```

Si Tesseract esta en una ubicacion no estandar, define `TESSERACT_CMD` con la
ruta completa de `tesseract.exe`.

Las reglas comunes se prueban con datos sinteticos. Las facturas reales se usan
solo de manera local para validar el resultado y nunca se incluyen en Git.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```

## Procesar una carpeta completa

Guarda los PDF en una carpeta privada y ejecuta:

```powershell
lectura-recibos-luz --folder facturas --output-dir salidas
```

Para desactivar el OCR o elegir idiomas:

```powershell
lectura-recibos-luz --folder facturas --output-dir salidas --no-ocr
lectura-recibos-luz --folder facturas --output-dir salidas --ocr-language spa+eng
```

En Windows, el lector también detecta automáticamente los idiomas instalados en
`%LOCALAPPDATA%\lectura-recibos-luz\tessdata`. Esto permite añadir
`spa.traineddata` sin necesitar permisos de administrador.

Se generan dos archivos privados:

- `salidas/historico_facturas.json`, con todos los datos estructurados;
- `salidas/informe_historico.html`, con resumen, evolucion, distribucion por
  periodos y detalle de facturas.

Las carpetas `facturas` y `salidas` estan excluidas de Git.

Las siguientes ejecuciones son incrementales: cada PDF se identifica por su
huella SHA-256, se omiten copias idénticas aunque tengan otro nombre y solo se
leen los archivos nuevos o modificados. El histórico conserva facturas ya
procesadas aunque el PDF original deje de estar en la carpeta. El resumen de la
ejecución indica nuevas, actualizadas, indexadas, duplicadas y errores.

## Comparar tarifas

Copia `ofertas.example.json` como `ofertas.private.json`, completa los precios y
ejecuta:

```powershell
lectura-recibos-luz --folder facturas --output-dir salidas --offers ofertas.private.json
```

Se crean `salidas/comparacion_tarifas.json` y
`salidas/comparacion_tarifas.html`. Todos los precios se expresan sin impuestos.
Una oferta solo muestra ahorro final cuando contiene energía, potencia,
servicios, otros costes, contador e impuestos. Si faltan datos, el informe
muestra únicamente el coste parcial conocido y señala los campos pendientes.

## Interfaz para Windows

Abre `Abrir Optimizador.cmd` con doble clic. La aplicación permite elegir las
carpetas, completar o cargar una oferta, procesar las facturas y abrir los dos
informes sin utilizar comandos. El formulario admite coma decimal y guarda la
oferta en `ofertas.private.json`, excluido de Git.

El botón `Buscar ofertas actuales` consulta únicamente páginas públicas
oficiales de Endesa, Naturgy y TotalEnergies. El consumo y las facturas permanecen
en el equipo. La aplicación guarda la URL y fecha de consulta, aplica las tarifas
al histórico local y muestra los supuestos utilizados. Una fuente que cambie de
formato se registra como error sin impedir que se comparen las demás.

El informe historico compara cada factura con la media de las tres anteriores y
genera alertas cuando el consumo aumenta al menos un 25%, el coste efectivo por
kWh sube al menos un 15% o el importe crece sin una variacion equivalente del
consumo. Cada aviso explica la causa probable y recomienda revisar el consumo,
la factura o buscar ofertas actuales.

También puede ejecutarse desde terminal:

```powershell
lectura-recibos-luz --folder facturas --output-dir salidas --search-offers
```

## Distribucion para Windows

El instalador incluye la aplicacion, Python, Tesseract y los idiomas OCR. En un
equipo instalado, los datos privados se crean en
`Documentos\OptimizadorFacturaElectrica`; nunca se guardan en la carpeta del
programa. El codigo fuente y el instalador no contienen facturas ni ofertas
privadas.

Durante cada proceso, la ventana muestra el avance por factura y guarda una
traza privada en `salidas\procesamiento.log` para poder diagnosticar esperas o
errores sin alterar los PDF originales.

En el primer inicio, un asistente propone las carpetas privadas y detecta una
ubicacion anterior cuando contiene facturas. Las rutas confirmadas se guardan
localmente y se recuperan en las siguientes aperturas.

Para generar una version desde el codigo fuente:

```powershell
python -m pip install pyinstaller
pyinstaller --noconfirm --clean packaging\lectura_recibos_luz.spec
iscc packaging\installer.iss
```
