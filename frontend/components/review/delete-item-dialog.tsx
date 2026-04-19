"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface DeleteItemDialogProps {
  open: boolean;
  itemName: string | null;
  onCancel: () => void;
  onConfirm: () => void;
}

export function DeleteItemDialog({
  open,
  itemName,
  onCancel,
  onConfirm,
}: DeleteItemDialogProps) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Remove this item?</DialogTitle>
          <DialogDescription>
            {itemName ? (
              <>
                <span className="font-medium text-slate-900">{itemName}</span>{" "}
                will be removed from the inventory. The change applies when you
                regenerate the packet.
              </>
            ) : (
              "This item will be removed from the inventory."
            )}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            className="bg-red-600 text-white hover:bg-red-700"
          >
            Remove
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
