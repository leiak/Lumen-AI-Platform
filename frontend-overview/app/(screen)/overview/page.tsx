// Compatibility shim: the original /overview route was the post-login target
// (see the deleted app/page.tsx redirector). Old links pushed to operators
// expect to land on the same dashboard, so we re-export the root page here
// instead of breaking them with a 404.
export { default } from "../page";
