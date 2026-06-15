import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export interface AddressValue {
  address: string;
  city: string;
  state: string;
  pincode: string;
  country: string;
}

export const EMPTY_ADDRESS: AddressValue = {
  address: "",
  city: "",
  state: "",
  pincode: "",
  country: "IN",
};

interface AddressFieldsProps {
  value: AddressValue;
  onChange: (v: AddressValue) => void;
}

export function AddressFields({ value, onChange }: AddressFieldsProps) {
  function set<K extends keyof AddressValue>(k: K, v: AddressValue[K]) {
    onChange({ ...value, [k]: v });
  }
  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div className="md:col-span-2">
        <Label htmlFor="address">Street address</Label>
        <Input
          id="address"
          value={value.address}
          onChange={(e) => set("address", e.target.value)}
          placeholder="123 Main Rd"
        />
      </div>
      <div>
        <Label htmlFor="city">City</Label>
        <Input
          id="city"
          value={value.city}
          onChange={(e) => set("city", e.target.value)}
          placeholder="Jaipur"
        />
      </div>
      <div>
        <Label htmlFor="state">State</Label>
        <Input
          id="state"
          value={value.state}
          onChange={(e) => set("state", e.target.value)}
          placeholder="Rajasthan"
        />
      </div>
      <div>
        <Label htmlFor="pincode">Pincode</Label>
        <Input
          id="pincode"
          inputMode="numeric"
          maxLength={6}
          value={value.pincode}
          onChange={(e) => set("pincode", e.target.value.replace(/\D/g, ""))}
          placeholder="302001"
        />
      </div>
      <div>
        <Label htmlFor="country">Country</Label>
        <Input
          id="country"
          value={value.country}
          onChange={(e) => set("country", e.target.value.toUpperCase())}
          maxLength={2}
        />
      </div>
    </div>
  );
}
