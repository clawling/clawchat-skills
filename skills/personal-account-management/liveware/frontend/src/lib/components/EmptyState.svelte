<script lang="ts">
  import WalletCardsIcon from "@lucide/svelte/icons/wallet-cards";
  import { Button } from "$lib/components/ui/button";

  type Props = {
    title: string;
    description: string;
    actionLabel?: string;
    onAction?: () => void;
    role?: "alert" | "status";
  };

  let { title, description, actionLabel, onAction, role }: Props = $props();
</script>

<div class="empty-state" {role} aria-live={role === "alert" ? "assertive" : undefined}>
  <div>
    <div class="empty-state__icon" aria-hidden="true">
      <WalletCardsIcon size={21} strokeWidth={1.8} />
    </div>
    <h2>{title}</h2>
    <p>{description}</p>
    {#if actionLabel && onAction}
      <div class="mt-5">
        <Button variant="outline" onclick={onAction}>{actionLabel}</Button>
      </div>
    {/if}
  </div>
</div>
