import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { Camera, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

interface PhotoUploadProps {
  /** Optional URL to persist; for the hackathon we store the data URL inline. */
  value: string | null;
  onChange: (v: string | null) => void;
  /** Surveyor mode: open the device camera directly. */
  capture?: boolean;
  className?: string;
}

export function PhotoUpload({
  value,
  onChange,
  capture,
  className,
}: PhotoUploadProps) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [preview, setPreview] = useState<string | null>(value);

  useEffect(() => setPreview(value), [value]);

  function pickFile(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result || "");
      setPreview(url);
      onChange(url);
    };
    reader.readAsDataURL(file);
  }

  return (
    <div className={cn("space-y-2", className)}>
      <Label>Photo {capture ? "(camera)" : "(optional)"}</Label>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture={capture ? "environment" : undefined}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          if (file) pickFile(file);
        }}
      />
      {preview ? (
        <div className="relative h-48 w-full overflow-hidden rounded-lg border">
          {/* eslint-disable-next-line jsx-a11y/alt-text */}
          <img src={preview} className="h-full w-full object-cover" />
          <button
            type="button"
            onClick={() => {
              setPreview(null);
              onChange(null);
              if (inputRef.current) inputRef.current.value = "";
            }}
            className="absolute right-2 top-2 grid size-7 place-items-center rounded-full bg-background/80 text-foreground shadow"
            aria-label="Remove photo"
          >
            <X className="size-4" />
          </button>
        </div>
      ) : (
        <Button
          type="button"
          variant="outline"
          className="h-24 w-full flex-col gap-1 border-dashed text-muted-foreground"
          onClick={() => inputRef.current?.click()}
        >
          <Camera className="size-5" />
          <span className="text-xs">
            {capture ? "Open camera" : "Upload a photo"}
          </span>
        </Button>
      )}
    </div>
  );
}
