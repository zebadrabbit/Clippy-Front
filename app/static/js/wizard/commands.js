/**
 * Command Pattern for Undo/Redo functionality
 * Manages timeline operations with full history
 */

export class CommandHistory {
  constructor() {
    this.undoStack = [];
    this.redoStack = [];
    this.maxHistory = 50;
  }

  execute(command) {
    command.execute();
    this.undoStack.push(command);
    this.redoStack = [];
    if (this.undoStack.length > this.maxHistory) {
      this.undoStack.shift();
    }
  }

  undo() {
    if (this.undoStack.length === 0) {
      console.log('[commands] Nothing to undo');
      return false;
    }
    const command = this.undoStack.pop();
    command.undo();
    this.redoStack.push(command);
    return true;
  }

  redo() {
    if (this.redoStack.length === 0) {
      console.log('[commands] Nothing to redo');
      return false;
    }
    const command = this.redoStack.pop();
    command.execute();
    this.undoStack.push(command);
    return true;
  }

  clear() {
    this.undoStack = [];
    this.redoStack = [];
  }

  canUndo() {
    return this.undoStack.length > 0;
  }

  canRedo() {
    return this.redoStack.length > 0;
  }
}

/**
 * Command: Add clip to timeline
 */
export function AddClipCommand(clipId, clipData, position, callbacks) {
  return {
    type: 'add',
    clipId,
    clipData,
    position,
    execute() {
      const list = document.getElementById('timeline-list');
      const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));

      if (callbacks && typeof callbacks.makeTimelineCard === 'function') {
        const card = callbacks.makeTimelineCard({
          clipId: this.clipId,
          ...this.clipData,
          kind: 'clip'
        });

        if (this.position === -1 || this.position >= cards.length) {
          const outro = list.querySelector('.timeline-card.timeline-outro');
          if (outro) {
            list.insertBefore(card, outro);
          } else {
            list.appendChild(card);
          }
        } else if (this.position === 0) {
          const intro = list.querySelector('.timeline-card.timeline-intro');
          if (intro) {
            intro.after(card);
          } else {
            list.insertBefore(card, cards[0]);
          }
        } else {
          cards[this.position - 1].after(card);
        }

        if (callbacks.rebuildSeparators) callbacks.rebuildSeparators();
        if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
        if (callbacks.updateArrangedConfirmState) callbacks.updateArrangedConfirmState();
      }
    },
    undo() {
      const list = document.getElementById('timeline-list');
      const card = list.querySelector(`.timeline-card[data-clip-id="${this.clipId}"]`);
      if (card) {
        this.cardHTML = card.outerHTML;
        card.remove();
        if (callbacks.rebuildSeparators) callbacks.rebuildSeparators();
        if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
        if (callbacks.updateArrangedConfirmState) callbacks.updateArrangedConfirmState();
      }
    }
  };
}

/**
 * Command: Remove clip from timeline
 */
export function RemoveClipCommand(clipId, clipData, position, callbacks) {
  return {
    type: 'remove',
    clipId,
    clipData,
    position,
    cardHTML: null,
    execute() {
      const list = document.getElementById('timeline-list');
      const card = list.querySelector(`.timeline-card[data-clip-id="${this.clipId}"]`);
      if (card) {
        this.cardHTML = card.outerHTML;
        card.remove();
        if (callbacks.rebuildSeparators) callbacks.rebuildSeparators();
        if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
        if (callbacks.updateArrangedConfirmState) callbacks.updateArrangedConfirmState();
      }
    },
    undo() {
      if (!this.cardHTML) return;

      const list = document.getElementById('timeline-list');
      const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));

      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = this.cardHTML;
      const card = tempDiv.firstChild;

      if (this.position >= cards.length) {
        const outro = list.querySelector('.timeline-card.timeline-outro');
        if (outro) {
          list.insertBefore(card, outro);
        } else {
          list.appendChild(card);
        }
      } else if (this.position === 0) {
        list.insertBefore(card, cards[0]);
      } else {
        cards[this.position - 1].after(card);
      }

      if (callbacks.rebuildSeparators) callbacks.rebuildSeparators();
      if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
      if (callbacks.updateArrangedConfirmState) callbacks.updateArrangedConfirmState();
    }
  };
}

/**
 * Command: Move clip in timeline
 */
export function MoveClipCommand(clipId, oldIndex, newIndex, callbacks) {
  return {
    type: 'move',
    clipId,
    oldIndex,
    newIndex,
    execute() {
      const list = document.getElementById('timeline-list');
      const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
      const card = cards.find(c => parseInt(c.dataset.clipId) === this.clipId);
      if (!card) return;

      const targetCard = cards[this.newIndex];
      if (targetCard && targetCard !== card) {
        if (this.newIndex > this.oldIndex) {
          targetCard.after(card);
        } else {
          targetCard.before(card);
        }
      }
      if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
    },
    undo() {
      const list = document.getElementById('timeline-list');
      const cards = Array.from(list.querySelectorAll('.timeline-card[data-clip-id]'));
      const card = cards.find(c => parseInt(c.dataset.clipId) === this.clipId);
      if (!card) return;

      const targetCard = cards[this.oldIndex];
      if (targetCard && targetCard !== card) {
        if (this.oldIndex > this.newIndex) {
          targetCard.after(card);
        } else {
          targetCard.before(card);
        }
      }
      if (callbacks.saveTimelineOrder) callbacks.saveTimelineOrder();
    }
  };
}
