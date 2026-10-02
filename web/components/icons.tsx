// Phosphor Icons (bold), inlined so there's no dependency
const PATHS = {
  check: "M232.49,80.49l-128,128a12,12,0,0,1-17,0l-56-56a12,12,0,1,1,17-17L96,183,215.51,63.51a12,12,0,0,1,17,17Z",
  x: "M208.49,191.51a12,12,0,0,1-17,17L128,145,64.49,208.49a12,12,0,0,1-17-17L111,128,47.51,64.49a12,12,0,0,1,17-17L128,111l63.51-63.52a12,12,0,0,1,17,17L145,128Z",
  arrow: "M224.49,136.49l-72,72a12,12,0,0,1-17-17L187,140H40a12,12,0,0,1,0-24H187L135.51,64.48a12,12,0,0,1,17-17l72,72A12,12,0,0,1,224.49,136.49Z",
};

export function Icon({ name, back, className = "h-3 w-3" }: { name: keyof typeof PATHS; back?: boolean; className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 256 256" fill="currentColor" className={`inline-block shrink-0 ${back ? "rotate-180" : ""} ${className}`}>
      <path d={PATHS[name]} />
    </svg>
  );
}
