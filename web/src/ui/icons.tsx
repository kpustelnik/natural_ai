// Inline stroke icons (24x24 grid, 1.75 stroke), so the UI needs no icon library.

import type { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function icon(paths: React.ReactNode) {
  return function Icon({ size = 16, ...rest }: IconProps) {
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth={1.75}
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
        {...rest}
      >
        {paths}
      </svg>
    );
  };
}

export const IconSearch = icon(
  <>
    <circle cx="11" cy="11" r="7" />
    <path d="m20 20-3.5-3.5" />
  </>,
);
export const IconLayers = icon(
  <>
    <path d="m12 3 9 5-9 5-9-5 9-5Z" />
    <path d="m3 13 9 5 9-5" />
  </>,
);
export const IconInfo = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 8h.01" />
  </>,
);
export const IconAlert = icon(
  <>
    <path d="M10.3 4.2 2.6 18a2 2 0 0 0 1.7 3h15.4a2 2 0 0 0 1.7-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
    <path d="M12 9v4M12 17h.01" />
  </>,
);
export const IconChevronDown = icon(<path d="m6 9 6 6 6-6" />);
export const IconChevronRight = icon(<path d="m9 6 6 6-6 6" />);
export const IconPlay = icon(<path d="M7 5v14l11-7L7 5Z" />);
export const IconPause = icon(<path d="M8 5v14M16 5v14" />);
export const IconClose = icon(<path d="M6 6l12 12M18 6 6 18" />);
export const IconFrame = icon(
  <>
    <path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4" />
    <circle cx="12" cy="12" r="2.5" />
  </>,
);
export const IconCopy = icon(
  <>
    <rect x="8" y="8" width="12" height="12" rx="2" />
    <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
  </>,
);
export const IconExternal = icon(
  <>
    <path d="M14 4h6v6M20 4l-9 9" />
    <path d="M18 14v4a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4" />
  </>,
);
export const IconCode = icon(<path d="m8 8-4 4 4 4M16 8l4 4-4 4M13 6l-2 12" />);
export const IconOrbit = icon(
  <>
    <path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Z" />
    <path d="m4 7.5 8 4.5 8-4.5M12 12v9" />
  </>,
);
export const IconPlan = icon(
  <>
    <rect x="4" y="4" width="16" height="16" rx="1.5" />
    <path d="M4 12h9M13 4v16" />
  </>,
);
export const IconReplay = icon(
  <>
    <rect x="3" y="5" width="18" height="14" rx="2" />
    <path d="m10 9 5 3-5 3V9Z" />
  </>,
);
export const IconSidebar = icon(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M9 4v16" />
  </>,
);
export const IconPanelRight = icon(
  <>
    <rect x="3" y="4" width="18" height="16" rx="2" />
    <path d="M15 4v16" />
  </>,
);
export const IconBuilding = icon(
  <>
    <path d="M4 21V5l8-2v18M12 7l8 2v12M3 21h18" />
    <path d="M7 8h2M7 12h2M7 16h2M15 12h2M15 16h2" />
  </>,
);
export const IconWalk = icon(
  <>
    <circle cx="13" cy="4.5" r="1.8" />
    <path d="m9 21 2.5-6.5L14 16v5M8 11l2-3.5 4 1 2 3.5h2.5M11.5 14.5 13 9" />
  </>,
);
export const IconRuler = icon(
  <>
    <path d="m3 16 13-13 5 5L8 21l-5-5Z" />
    <path d="m7 12 2 2M10 9l2 2M13 6l2 2" />
  </>,
);
export const IconUp = icon(<path d="m6 15 6-6 6 6" />);
export const IconDown = icon(<path d="m6 9 6 6 6-6" />);
export const IconEnter = icon(
  <>
    <path d="M10 4h8a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-8" />
    <path d="m11 8 4 4-4 4M4 12h11" />
  </>,
);
export const IconCamera = icon(
  <>
    <path d="M4 8h3l2-3h6l2 3h3v11H4z" />
    <circle cx="12" cy="13" r="3.5" />
  </>,
);
export const IconHelp = icon(
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .9-1 1.6V14M12 17.5v.01" />
  </>,
);
export const IconPresent = icon(<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" />);
