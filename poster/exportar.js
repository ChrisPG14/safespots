// Exporta poster.html a poster.pdf (600 × 1600 mm) y a una vista previa PNG.
// Uso: node exportar.js   (requiere Playwright con Chromium)
const path = require('path');
const { chromium } = require('playwright');

(async () => {
  const navegador = await chromium.launch();
  const pagina = await navegador.newPage();
  await pagina.goto('file://' + path.join(__dirname, 'poster.html'), { waitUntil: 'networkidle' });

  // Aviso si algún bloque se sale del alto oficial.
  const desborde = await pagina.evaluate(() => {
    const main = document.querySelector('main');
    const pie = { getBoundingClientRect: () => ({ top: document.body.getBoundingClientRect().bottom - 24 * 3.7795 }) }; // margen inferior de 24 mm
    return main.getBoundingClientRect().bottom - pie.getBoundingClientRect().top;
  });
  console.log(desborde > 0 ? `DESBORDA ${desborde.toFixed(0)} px` : `Holgura ${(-desborde).toFixed(0)} px`);

  await pagina.pdf({ path: path.join(__dirname, 'poster.pdf'), width: '600mm', height: '1600mm', printBackground: true, pageRanges: '1' });
  await pagina.setViewportSize({ width: 2268, height: 6047 }); // 600 × 1600 mm a 96 ppp
  await pagina.screenshot({ path: path.join(__dirname, 'vista-previa.png'), scale: 'css' });
  await navegador.close();
})();
