(() => {
  'use strict';

  const load = src => new Promise(resolve => {
    const script = document.createElement('script');
    script.src = src;
    script.onload = resolve;
    script.onerror = resolve;
    document.head.appendChild(script);
  });

  async function start() {
    await load('production22.js');
    await load('production23.js');
  }

  start();
})();
