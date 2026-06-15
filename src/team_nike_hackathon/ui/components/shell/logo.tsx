import { Link } from "@tanstack/react-router";

interface LogoMarkProps {
  size?: number;
  /** Show rounded-square tile background */
  tile?: boolean;
  className?: string;
}

export function LogoMark({ size = 48, tile = true, className }: LogoMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 200 200"
      xmlns="http://www.w3.org/2000/svg"
      aria-label="MatchCare logo mark"
      className={className}
    >
      {tile && (
        <>
          <rect width="200" height="200" rx="44" fill="#0B2D48" />
          <rect
            width="200"
            height="200"
            rx="44"
            fill="none"
            stroke="rgba(255,255,255,0.06)"
            strokeWidth="2"
          />
        </>
      )}
      <path
        d="M100,148 C 78,133 52,114 52,84 C 52,66 66,56 80,56 C 89,56 96,61 100,68 Z"
        fill="#E8796B"
      />
      <path
        d="M100,68 C 104,61 111,56 120,56 C 134,56 148,66 148,84 C 148,114 122,133 100,148 Z"
        fill="#3BBFB0"
      />
      <line
        x1="100"
        y1="56"
        x2="100"
        y2="148"
        stroke={tile ? "#0B2D48" : "transparent"}
        strokeWidth="2"
      />
      <polyline
        points="54,94 67,94 73,76 80,114 88,88 100,88 112,88 120,114 127,76 133,94 146,94"
        fill="none"
        stroke="white"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.92"
      />
      <circle cx="100" cy="88" r="3.5" fill="white" opacity="0.95" />
    </svg>
  );
}

interface LogoProps {
  to?: string;
  size?: "sm" | "md" | "lg";
  /** Hide the wordmark and tagline; show only the mark. */
  markOnly?: boolean;
  className?: string;
}

const sizeMap = {
  sm: { icon: 28, name: "text-base", sub: "text-[8px]" },
  md: { icon: 38, name: "text-xl", sub: "text-[10px]" },
  lg: { icon: 56, name: "text-3xl", sub: "text-xs" },
} as const;

export function Logo({
  to = "/",
  size = "md",
  markOnly = false,
  className = "",
}: LogoProps) {
  const s = sizeMap[size];
  const gap = Math.round(s.icon * 0.37);

  const content = (
    <div
      className={`flex items-center ${className}`}
      style={{ gap: `${gap}px` }}
    >
      <LogoMark size={s.icon} tile />
      {!markOnly && (
        <div>
          <div className="flex items-baseline leading-none">
            <span
              className={`${s.name} font-bold tracking-tight text-[#E8796B]`}
            >
              match
            </span>
            <span
              className={`${s.name} font-bold tracking-tight text-[#0B2D48] dark:text-white`}
            >
              care
            </span>
          </div>
          <p
            className={`${s.sub} mt-1 font-medium uppercase tracking-[0.14em] text-[#7A99B0]`}
          >
            Your provider, perfectly matched
          </p>
        </div>
      )}
    </div>
  );

  if (to) {
    return (
      <Link to={to} className="transition-opacity hover:opacity-80">
        {content}
      </Link>
    );
  }

  return content;
}

export default Logo;
