"use client";

// This component must be used before any React hydration occurs.
// In App Router, place in layout.tsx <head> via Next.js script loading.
// For now, we use a workaround that patches before React's console.error override.

export function ResizeObserverSuppressor() {
  return (
    <script
      dangerouslySetInnerHTML={{
        __html: `
(function(){
  var originalError=console.error.bind(console);
  var suppressed=['ResizeObserver','children','is empty','__nextjs_original-stack-frame','antd: compatible','React is 16 ~ 18'];
  console.error=function(){
    var msg=arguments[0];
    if(typeof msg==='string'&&suppressed.some(function(s){return msg.indexOf(s)!==-1;})){
      return;
    }
    originalError.apply(console,arguments);
  };
  window.onerror=function(msg){
    if(typeof msg==='string'&&msg.indexOf('ResizeObserver')!==-1){return true;}
  };
})();
        `,
      }}
    />
  );
}
