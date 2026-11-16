async (page) => {
  return await page.evaluate(() => ({
    secureContext:window.isSecureContext,
    samples:window.__xiaolinSamples || [],
    events:window.__xiaolinEvents || [],
    model:document.querySelector('#model-tag')?.textContent,
    message:document.querySelector('#message')?.textContent
  }));
}
