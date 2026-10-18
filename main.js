// main.js: confirmation modal, undo toast auto-hide, timer start/stop
document.addEventListener('DOMContentLoaded', function(){
  const modal = document.getElementById('confirm-modal');
  const modalOverlay = modal && modal.querySelector('.modal-overlay');
  const btnYes = document.getElementById('confirm-yes');
  const btnNo = document.getElementById('confirm-no');
  let pendingDeleteUrl = null;

  function openModal(url){
    pendingDeleteUrl = url;
    modal.style.display = 'flex';
    modal.setAttribute('aria-hidden','false');
    btnYes.focus();
  }

  function closeModal(){
    pendingDeleteUrl = null;
    modal.style.display = 'none';
    modal.setAttribute('aria-hidden','true');
  }

  document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', function(e){
      e.preventDefault();
      const url = btn.getAttribute('data-delete-url');
      openModal(url);
    });
  });

  if(btnYes){
    btnYes.addEventListener('click', function(){
      if(pendingDeleteUrl){
        window.location.href = pendingDeleteUrl;
      }
    });
  }

  if(btnNo){
    btnNo.addEventListener('click', closeModal);
  }

  if(modalOverlay){
    modalOverlay.addEventListener('click', closeModal);
  }

  document.addEventListener('keydown', function(e){
    if(e.key === 'Escape' && modal && modal.style.display === 'flex') closeModal();
  });

  function setMenuState(dropdown, button, open){
    if (!dropdown) return;
    dropdown.setAttribute('aria-hidden', open ? 'false' : 'true');
    dropdown.style.display = open ? 'block' : 'none';
    if (button) {
      button.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
  }

  function bindMenu(menuRoot, triggerSelector, dropdownSelector){
    const button = menuRoot.querySelector(triggerSelector);
    const dropdown = menuRoot.querySelector(dropdownSelector);
    if (!button || !dropdown) return;

    button.addEventListener('click', function(e){
      e.stopPropagation();
      const open = dropdown.getAttribute('aria-hidden') === 'true';
      setMenuState(dropdown, button, open);
    });

    document.addEventListener('click', function(ev){
      if (!menuRoot.contains(ev.target)) {
        setMenuState(dropdown, button, false);
      }
    });
  }

  document.querySelectorAll('.nav-menu').forEach(menu => bindMenu(menu, '.nav-btn', '.nav-dropdown'));
  document.querySelectorAll('.plus-menu').forEach(menu => bindMenu(menu, '.menu-btn-plus', '.menu-dropdown'));
  document.querySelectorAll('.profile-menu').forEach(menu => bindMenu(menu, '.menu-btn', '.menu-dropdown'));

  const timers = {};
  document.querySelectorAll('.timer-start').forEach(btn => {
    btn.addEventListener('click', function(){
      const id = btn.getAttribute('data-task-id');
      if(timers[id]){
        clearInterval(timers[id].interval);
        const seconds = Math.round((Date.now() - timers[id].start)/1000);
        fetch('/log_time/' + id, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({seconds: seconds})});
        const el = document.getElementById('time-' + id);
        if(el){
          const prev = parseInt(el.textContent.replace('s','')) || 0;
          el.textContent = (prev + seconds) + 's';
        }
        delete timers[id];
        btn.textContent = '⏱';
      } else {
        timers[id] = { start: Date.now() };
        btn.textContent = '■';
        timers[id].interval = setInterval(()=>{},1000);
      }
    });
  });

  const flash = document.getElementById('flash-container');
  if(flash){
    setTimeout(()=>{ flash.style.display='none'; }, 6000);
  }

  const studyDurationInput = document.getElementById('study-timer-duration');
  const studyTimerDisplay = document.getElementById('study-timer-display');
  const studyTimerToggle = document.getElementById('study-timer-toggle');
  const studyTimerReset = document.getElementById('study-timer-reset');

  if (studyDurationInput && studyTimerDisplay && studyTimerToggle && studyTimerReset) {
    let studyTimerId = null;
    let studyTimeLeft = Number(studyDurationInput.value || 25) * 60;

    const formatTime = (seconds) => {
      const mins = Math.floor(seconds / 60);
      const secs = seconds % 60;
      return String(mins).padStart(2, '0') + ':' + String(secs).padStart(2, '0');
    };

    const updateStudyDisplay = () => {
      studyTimerDisplay.textContent = formatTime(studyTimeLeft);
      studyTimerDisplay.classList.toggle('is-warning', studyTimeLeft <= 60 && studyTimeLeft > 0);
      studyTimerDisplay.classList.toggle('is-complete', studyTimeLeft === 0);
    };

    const setTimerRunningState = (isRunning) => {
      studyTimerDisplay.classList.toggle('running', isRunning);
      studyTimerToggle.textContent = isRunning ? 'Pause' : 'Start';
      studyTimerDisplay.classList.toggle('is-warning', !isRunning && studyTimeLeft <= 60 && studyTimeLeft > 0);
    };

    const stopStudyTimer = () => {
      if (studyTimerId) {
        clearInterval(studyTimerId);
        studyTimerId = null;
      }
      setTimerRunningState(false);
    };

    studyDurationInput.addEventListener('change', () => {
      if (!studyTimerId) {
        const durationMinutes = Math.max(1, Number(studyDurationInput.value || 25));
        studyTimeLeft = durationMinutes * 60;
        updateStudyDisplay();
      }
    });

    studyTimerToggle.addEventListener('click', () => {
      if (studyTimerId) {
        stopStudyTimer();
        return;
      }

      const durationMinutes = Math.max(1, Number(studyDurationInput.value || 25));
      if (studyTimeLeft <= 0 || studyTimeLeft >= durationMinutes * 60) {
        studyTimeLeft = durationMinutes * 60;
      }

      setTimerRunningState(true);
      studyTimerId = setInterval(() => {
        if (studyTimeLeft > 0) {
          studyTimeLeft -= 1;
          updateStudyDisplay();
        } else {
          clearInterval(studyTimerId);
          studyTimerId = null;
          studyTimerDisplay.classList.remove('running');
          studyTimerDisplay.classList.add('is-complete');
          studyTimerToggle.textContent = 'Start';
          studyTimerDisplay.textContent = '00:00';
          alert('Study session complete — great work!');
        }
      }, 1000);
    });

    studyTimerReset.addEventListener('click', () => {
      stopStudyTimer();
      const durationMinutes = Math.max(1, Number(studyDurationInput.value || 25));
      studyTimeLeft = durationMinutes * 60;
      studyTimerDisplay.classList.remove('is-complete', 'is-warning');
      updateStudyDisplay();
    });

    updateStudyDisplay();
  }
});
