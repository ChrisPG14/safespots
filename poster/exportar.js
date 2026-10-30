// Genera, a partir de poster.html:
//   SafeSpots_Cartel.pdf   archivo para imprimir (600 x 1600 mm)
//   SafeSpots_Cartel.html  versión editable en un solo archivo (imágenes incluidas)
// Uso: node exportar.js [carpeta-vista-previa]
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const dir = __dirname;
const tipos = { '.jpg': 'image/jpeg', '.png': 'image/png', '.svg': 'image/svg+xml' };

// Versión editable autocontenida.
const fuente = fs.readFileSync(path.join(dir, 'poster.html'), 'utf8');
const editable = fuente.replace(/src="(figuras\/[^"]+)"/g, (_, ruta) => {
  const datos = fs.readFileSync(path.join(dir, ruta)).toString('base64');
  return `src="data:${tipos[path.extname(ruta)]};base64,${datos}"`;
});
fs.writeFileSync(path.join(dir, 'SafeSpots_Cartel.html'), editable);

(async () => {
  const navegador = await chromium.launch();
  const pagina = await navegador.newPage();
  await pagina.emulateMedia({ media: 'print' });
  await pagina.goto('file://' + path.join(dir, 'SafeSpots_Cartel.html'), { waitUntil: 'networkidle' });
  const holgura = await pagina.evaluate(() =>
    (document.querySelector('.fecha').getBoundingClientRect().top -
     document.querySelector('.cuerpo').getBoundingClientRect().bottom) / 3.7795);
  console.log(holgura < 0 ? `NO CABE: sobran ${(-holgura).toFixed(0)} mm` : `Cabe, holgura ${holgura.toFixed(0)} mm`);
  await pagina.pdf({ path: path.join(dir, 'SafeSpots_Cartel.pdf'), width: '600mm', height: '1600mm', printBackground: true, pageRanges: '1' });
  if (process.argv[2]) {
    await pagina.setViewportSize({ width: 2268, height: 6047 });
    await pagina.screenshot({ path: path.join(process.argv[2], 'vista.png'), clip: { x: 0, y: 0, width: 2268, height: 6047 } });
  }
  await navegador.close();
})();
