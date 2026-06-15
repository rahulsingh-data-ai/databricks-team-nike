import { ModeToggle } from "@/components/shell/mode-toggle";
import Logo from "@/components/shell/logo";
import { ReactNode } from "react";

interface NavbarProps {
  leftContent?: ReactNode;
  rightContent?: ReactNode;
}

export function Navbar({ leftContent, rightContent }: NavbarProps) {
  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/80 backdrop-blur-md">
      <div className="flex h-20 w-full items-center justify-between px-6 md:px-10">
        {leftContent || <Logo size="md" />}
        {rightContent || <ModeToggle />}
      </div>
    </header>
  );
}

export default Navbar;
