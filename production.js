(() => {
  'use strict';
  const script=document.createElement('script');
  script.src='production24.js';
  script.onerror=()=>console.error('Production 2.4 UI failed to load.');
  document.head.appendChild(script);
})();
