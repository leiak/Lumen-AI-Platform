/** CSS module type stub.
 *  esbuild's `loader: { ".css": "text" }` config resolves CSS
 *  imports to strings at bundle time. tsc doesn't know about that,
 *  so we declare `*.css` as string here. Mirrors what the bundler
 *  produces. */
declare module "*.css" {
  const css: string;
  export default css;
}
