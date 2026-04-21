async page => {
  await page.goto('http://localhost:5173/war-room');
  await page.setViewportSize({ width: 1280, height: 1080 });
  await page.waitForTimeout(4000);
  const sinopac = page.getByText('Sinopac (sinopac-main)');
  if (await sinopac.count() > 0) await sinopac.click();
  await page.waitForTimeout(2000);
  await page.screenshot({ path: 'fullpage.png', fullPage: true, scale: 'css' });
}
