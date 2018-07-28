# -*- coding: utf-8 -*-
# ==============================================================================
# Voty initadmin views/actions
# ==============================================================================
#
# parameters (*default)
# ------------------------------------------------------------------------------

from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.models import Permission, Group, User
from django.contrib import messages
from django.contrib.sites.models import Site
from django.core.exceptions import PermissionDenied
from django.core.mail import EmailMessage
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
from django.db.models import Q
from django.db.models.functions import Upper
from django.shortcuts import render, get_object_or_404, redirect
from django.utils.translation import ugettext as _
from django.utils import six
from django.utils import translation
from django.utils.html import escape, strip_tags

import account.views
import uuid
from pinax.notifications.models import send as notify
from notifications.models import Notification
from account.models import SignupCodeResult, SignupCode

from .models import InviteBatch, UserConfig
from .forms import (UploadFileForm, LoginEmailOrUsernameForm, UserEditForm,
  UserModerateForm, UserValidateLocalisationForm, UserActivateForm, UserDeleteForm,
  UserGiveGroupPrivilegeForm, ListboxSearchForm, UserLocaliseForm, UserInviteForm,
  UserLanguageForm, DeleteSignupCodeForm, CustomPasswordChangeForm, UserDeleteAccount)

from datetime import datetime, timedelta
from uuid import uuid4
from dal import autocomplete
from io import StringIO, TextIOWrapper
import csv

# --------------------- Group Permission decorator -----------------------------
# Poor man's decorator, use: @group_required("[group-name]")
# https://djangosnippets.org/snippets/10508/
def group_required(group, login_url=None, raise_exception=False):
  def check_perms(user):
    if isinstance(group, six.string_types):
      groups = (group, )
    else:
      groups = group

    if user.groups.filter(name__in=groups).exists():
      return True

    if raise_exception:
        raise PermissionDenied
    return False
  return user_passes_test(check_perms, login_url=login_url)

# --------------------- Get notification recipient list ------------------------
def _get_recipient_list(permission):
  localisation_permission = Permission.objects.filter(codename=permission)
  recipient_list = User.objects.filter(groups__permissions=localisation_permission,is_active=True).distinct()
  return recipient_list

# ------------------------- Update UserNotifications ---------------------------
def _update_notifications_and_flags(current_flag, permission):
  flag_list = [x for x in current_flag.split(";") if x.startswith(permission)]
  flag_update = current_flag
  if len(flag_list) > 0:
    for flag in flag_list:

      # remove all related flag from this users config
      flag_update = flag_update.replace("".join([flag, ";"]), "")

      # XXX data stored as JSON but couldn't figure out how to search
      # XXX only way to access data is x.data["flag"], so filter() won't work
      # XXX this can be costly
      # https://docs.djangoproject.com/en/1.10/ref/contrib/postgres/fields/#std:fieldlookup-hstorefield.contains
      for note in Notification.objects.all():
        if note.data["flag"] == flag:
          note.delete()
  return flag_update

# -------------------------- Invite single user -------------------------------- 
def _invite_single_user(first_name, email_address, site):
  try:
    code = SignupCode.objects.get(email=email_address)
    new_addition = False

  # XXX a bit lame to catchall including invalid (expired) codes. For now...
  except (SignupCode.DoesNotExist, SignupCode.InvalidCode):
    code = SignupCode(
      email=email_address,
      code=uuid4().hex[:20],
      max_uses=1,
      sent=datetime.utcnow(),
      expiry=datetime.utcnow() + timedelta(days=1)
    )
    new_addition = True
    code.save()

    EmailMessage(
      render_to_string("initadmin/email_invite_subject.txt"),
      render_to_string(
        "initadmin/email_invite_message.txt",
        context=dict(
          domain=site.domain,
          code=code,
          first_name=first_name,
          platform_title=settings.PLATFORM_TITLE
        )
      ),
      settings.DEFAULT_FROM_EMAIL,
      [email_address]
    ).send()
  

  return code, new_addition

# ------------------------- Invite multiple users ------------------------------
def _invite_batch_users(csv_file):
  site = Site.objects.get_current()
  total = newly_added = 0
  reader = list(csv.reader(csv_file, delimiter=";"))
  results = StringIO()

  # create file for InviteBatch
  writer = csv.DictWriter(
    results,
    delimiter=";",
    fieldnames=["first_name", "last_name", "email_address", "invite_code"]
  )
  writer.writeheader()

  for row in reader:
    total += 1
    first_name = row[0]
    last_name = row[1]
    email_address = row[2]

    sent_with_code, new_addition = _invite_single_user(first_name, email_address, site)

    if new_addition:
      newly_added += 1

    writer.writerow({
      "first_name": first_name,
      "last_name": last_name,
      "email_address": email_address,
      "invite_code": sent_with_code.code
    })

  InviteBatch(
    payload=results.getvalue(),
    total_found=total,
    new_added=newly_added
  ).save()

  return total, newly_added

#
# ____    ____  __   ___________    __    ____   _______.
# \   \  /   / |  | |   ____\   \  /  \  /   /  /       |
#  \   \/   /  |  | |  |__   \   \/    \/   /  |   (----`
#   \      /   |  | |   __|   \            /    \   \    
#    \    /    |  | |  |____   \    /\    / .----)   |   
#     \__/     |__| |_______|   \__/  \__/  |_______/    
#
#                                                       

# ---------------------------- LoginView ---------------------------------------
class LoginView(account.views.LoginView):
  form_class = LoginEmailOrUsernameForm

# ---------------------- SignupCode (Autocomplete) -----------------------------
class SignupCodeAutocomplete(autocomplete.Select2QuerySetView):

  def get_queryset(self):
    if not self.request.user.is_authenticated():
      return SignupCode.objects.none()

    qs = SignupCode.objects.all()
    if self.q:
      qs = qs.filter(email__icontains=self.q)
    return qs

  def get_result_label(self, item):
    return render_to_string(
      "fragments/autocomplete/signupcode_item.html",
      context=dict(item=item)
    )

# -------------------------- Notification List  --------------------------------
def notification_list(request):
  user = get_object_or_404(get_user_model(), id=request.user.id)

  # handled by pinax 
  return render(request, "pinax/notifications/list.html", {
    "notifications": request.user.notifications
  })

# -------------------------- Initiative List  ----------------------------------
def initiative_list(request):
  return render(request, "Hello Initiative List", context={})

# ---------------------------- User List  --------------------------------------
@login_required
@group_required(settings.PLATFORM_GROUP_VALUE_TITLE_LIST, raise_exception=True)
def user_list(request):

  user_values = {}
  user_list = get_user_model().objects.filter(is_superuser=False, is_staff=False).exclude(username__istartswith="deleted")
  user_filters = {
    "glossary_active_all": True,
    "glossary_active_flag": True,
    "glossary_char_list": settings.LISTBOX_OPTION_DICT.GLOSSARY_CHAR_LIST
  }
  number_of_records = settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_DEFAULT

  if "scope" in request.GET:
    request_scope = request.GET["scope"]
    for scope in settings.CATEGORIES.SCOPE_CHOICES:
      if scope[0] == request_scope:
        user_list = user_list.filter(config__scope__istartswith=request_scope).distinct()
        user_values["scope"] = request_scope

  if "search" in request.GET:
    request_search = escape(strip_tags(request.GET["search"]))
    user_list = user_list.filter(
      Q(first_name__icontains=request_search) |
      Q(last_name__icontains=request_search) |
      Q(username__icontains=request_search) |
      Q(email__icontains=request_search)
    ).distinct()
    user_values["search"] = request_search

  # by now we have the relevant user set, flag available characters

  # XXX glossary assumes we are searching for username, should be settable
  # XXX missing summarizing all $%&/( into #
  glossary_candidate_list = [getattr(x[1], "username", None) for x in enumerate(user_list)]
  glossary_candidate_list = list(set([x[0].upper() for x in glossary_candidate_list if x is not None]))

  for glossy_character in glossary_candidate_list:
    try:
      user_filters["glossary_char_list"][glossy_character]["avail"] = True
    except:
      user_filters["glossary_char_list"]["#"]["avail"] = True

  # check if users have flags set and enable the character
  for user in user_list:
    if len(user.config.is_flagged) > 0:
      glossary_candidate_list.append("flagged")
      user_filters["glossary_active_flag"] = False
      user_filters["glossary_char_list"]["flagged"] = {"avail":True}
      break

  # filter user_list if a glossary is passed in the request
  if "glossary" in request.GET:
    request_glossy_character = request.GET["glossary"]
    if request_glossy_character != "":
      regex_azAZ = r"^[a-zA-Z]"
    
      # XXX refactor
      # XXX why are active chars sticky and a reload does not remove them?
      for glossy_character in glossary_candidate_list:
        if glossy_character == request_glossy_character:
          if request_glossy_character == "#":
            user_list = user_list.exclude(username__regex=regex_azAZ)
            del user_filters["glossary_char_list"]["#"]["avail"]
            del user_filters["glossary_active_all"]
          elif request_glossy_character == "flagged":
            user_list = user_list.exclude(config__is_flagged__isnull=True).exclude(config__is_flagged__exact="")
            del user_filters["glossary_active_all"]
            user_filters["glossary_active_flag"] = True
            del user_filters["glossary_char_list"]["flagged"]["avail"]
          else:
            user_list = user_list.filter(username__istartswith=glossy_character)
            del user_filters["glossary_char_list"][glossy_character]["avail"]
            del user_filters["glossary_active_all"]

  # always convert glossary_char_list into parseable format
  user_filters["glossary_char_list"] = [user_filters["glossary_char_list"][x] for x in user_filters["glossary_char_list"]]

  # XXX sorting defaults to username, add sorting, add default/asc/desc to settings
  if "sort" in request.GET:
    pass
    #request_sort = request.GET["sort"]
    #for sortation in settings.SORT_OPITION_LIST:
    #  if request_sort["field"] == sortation
    #    if request_sort["dir"] == "DESC":
    #      user_list.order_by(request_sort).reverse()
    #    else:
    #      user_list.order_by(request_sort)
    #user_values["sort"] = request_sort
  else:
    user_list = user_list.order_by("username")

  if "records" in request.GET:
    request_records = request.GET["records"]
    if request_records.isdigit():
      for record_opt in settings.LISTBOX_OPTION_DICT.NUMBER_OF_RECORDS_OPTION_LIST:
        if record_opt[0] == request_records:
          number_of_records = request_records
          user_values["records"] = request_records

  paginator = Paginator(user_list, number_of_records)
  page = request.GET.get("page")
  form = ListboxSearchForm(initial=user_values)
    
  try:
    users = paginator.page(page)
  except PageNotAnInteger:
    users = paginator.page(1)
  except EmptyPage:
    users = paginator.page(paginator.num_pages)

  return render(request, "initadmin/list_users.html", {
    "paginator": paginator,
    "users" :users,
    "user_filters": user_filters,
    "form": form
    }
  )

# =============================== Add Users ====================================
@login_required
@group_required(settings.PLATFORM_GROUP_VALUE_TITLE_LIST, raise_exception=True)
def user_invite(request):
  if request.method == "POST":

    # ----------------------- Invite Single User -------------------------------
    if request.POST.get("action", None) == "invite_user":
      if request.user.has_perm("auth.user_can_invite"):
        form = UserInviteForm(request.POST)
        if form.is_valid():
          email_address = request.POST.get("email")
          code, is_new = _invite_single_user(
            request.POST.get("first_name"),
            email_address,
            Site.objects.get_current()
          )
          if is_new == True:
            messages.success(request, "".join([
              _("Invitation sent to"), ": ",
              "{}".format(email_address)
            ]))
          else:
            messages.warning(request, _("Could not send invitation. Please remove existing signup code first."))
  
    # ---------------------- Invite Batch User ---------------------------------
    elif request.POST.get("action", None) == "invite_batch":
      if request.user.has_perm("auth.user_can_invite"):
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
          total, sent = _invite_batch_users(TextIOWrapper(request.FILES['file'].file, encoding=request.encoding))
          messages.success(request, "".join(["{}/{} ".format(sent, total), _("(sent/total) invitations were sent.")]))

    # ------------------------- Delete Signup Code -----------------------------
    elif  request.POST.get("action", None) == "delete_signup":
      if request.user.has_perm("auth.user_can_invite"):
        form = DeleteSignupCodeForm(request.POST)
        if form.is_valid():
          id = request.POST.get("id")
          signup = SignupCode.objects.get(id=id)
          email = signup.email
          signup.delete()
          messages.success(request, "".join([_("Removed Signup Code for"), ": ", "{}".format(email)]))

    return redirect("/backoffice/invite/")
  else:
    form_upload = UploadFileForm()
    form_invite = UserInviteForm()
    form_remove = DeleteSignupCodeForm()

  return render(request, "initadmin/invite_user.html", context={
    "form_upload": form_upload,
    "form_invite": form_invite,
    "form_remove": form_remove,
    "invitebatches": InviteBatch.objects.order_by("-created_at")
  })

# ========================== Moderate User =====================================
@login_required
@group_required(settings.PLATFORM_GROUP_VALUE_TITLE_LIST, raise_exception=True)
def user_view(request, user_id):

  # the user being edited  
  user = get_object_or_404(get_user_model(), pk=user_id)

  if request.method == "POST":

    # -------------------------- Set/Reset Email -------------------------------
    if request.POST.get("action", None) == "reset_email":
      if request.user.has_perm("auth.user_can_reset"):

        new_email = request.POST.get("email")
        if user.email == "":
          existing_user_list = User.objects.filter(email=new_email)
          if len(existing_user_list) > 0:
            messages.warning(request, "".join([
              _("Cannot associate email with this user, because it is already used by (username): "),
              existing_user_list[0].username
            ]))
            return redirect("/backoffice/users/%s" % (user.id))
          user.email = new_email
          user.save()
  
        # hijack auth password reset
        email_form = PasswordResetForm({"email": new_email})
        if email_form.is_valid():
          email_form.save()
          messages.success(request, _("Email updated and password reset link sent."))

    # --------------------- Add/Remove Custom Group ----------------------------
    elif request.POST.get("action", None) == "give_group_privileges":
      if request.user.has_perm("auth.user_can_nominate"):

        user.groups.clear()
        new_group_list = []
        for key, value in request.POST.items():
          if key.startswith("groups"):
            group = Group.objects.get(id=int(key.split("_")[1]))
            if group:
              new_group_list.append(group.name)
              user.groups.add(group)
        user.save()
        messages.success(request, "".join([_("Added the user to the following groups:"), ", ".join(new_group_list)]))

    # ----------------------- Validate Localisation ----------------------------
    elif request.POST.get("action", None) == "validate_scope":
      if request.user.has_perm("auth.user_can_localise"):

        # prevent tempering
        #if request.POST.get("scope", None) !== user.config.scope:
        #  messages.warning(request, _("You are not allowed to modify the localisation chosen by a user. Please only validate/invalidate the chose localisation"))
        #  return redirect("/backoffice/users/%s" % (user.id))
        if user_id == request.user.id:
          message.warning(_("You cannot validate your own localisation change. Please have another team member review your request."))
          return redirect("/backoffice/users/%s" % (user.id))
  
        user_config = UserConfig.objects.get(user_id=user_id)
        user_config.is_flagged = _update_notifications_and_flags(user_config.is_flagged, "user_can_localise")
        user_config.scope = request.POST.get("scope", "eu")
        user_config.is_scope_confirmed = int(request.POST.get("is_scope_confirmed", 0))
        user_config.save()
        messages.success(request, _("Successfully updated user localisation."))
        notify([user], settings.NOTIFICATIONS.MODERATE.USER_LOCALISATION_ACCEPTED, {
          "description": "".join([_("Localisation validated. New location: "), user.config.scope, "."]),
        }, sender=request.user)

    # ---------------------- Activate/Disactivate Account ----------------------
    elif request.POST.get("action", None) == "activate_account":
      if request.user.has_perm("auth.user_can_activate"):

        user.is_active = request.POST.get("status")
        user.save()
        messages.success(request, _("User account status was changed."))

    # --------------------- Delete account permanently -------------------------
    elif request.POST.get("action", None) == "delete_account":
      if request.user.has_perm("auth.user_can_delete"):
        if user.is_active == True:
          messages.warning(request, _("You cannot delete a user whose account is still in active state. Please disactivate the account first."))
        elif request.POST.get("username") != user.username:
          messages.warning(request, _("Username does not match. Please provide the correct username."))
        else:

          # clear flags associated with deletion request, reset config 
          user_config = UserConfig.objects.get(user_id=user_id)
          user_config.is_flagged = _update_notifications_and_flags(user_config.is_flagged, "user_can_delete")
          user_config.scope = "eu"
          user_config.save()

          # it's not possible to set authorship to a single deleted user, because
          # for example an Initiative cannot have multiple supporters which are 
          # the same (deleted) user. So the user is kept but anonymized.
          user.email = ""
          user.username = "".join(["deleted_user" + str(user.id)])
          user.first_name = ""
          user.last_name = ""
          user.save()
          messages.success(request, _("User was deleted from database and his contributions change to author 'Deleted User'."))
          return redirect("/backoffice/users")

    return redirect("/backoffice/users/%s" % (user.id))

  else:
    form_user_moderate = UserModerateForm(initial={
      "first_name": user.first_name,
      "last_name": user.last_name,
      "username": user.username,
      "email": user.email
    })
    form_user_addgroup = UserGiveGroupPrivilegeForm()
    groups = {}
    for group in Group.objects.all():
      if user.groups.filter(name=group.name).exists():
        groups[group.id] = "checked=checked"
      else:
        groups[group.id] = ""
    form_user_addgroup.fields["groups"].choices=[(x.id, x.name, groups[x.id]) for x in Group.objects.all()]
    form_user_validate = UserValidateLocalisationForm(initial={
      "scope": user.config.scope,
      "is_scope_confirmed": user.config.is_scope_confirmed
    })
    last_login = getattr(user, "last_login", None)
    form_user_activate = UserActivateForm(initial={
      "is_active": user.is_active,
      "last_login": last_login.strftime("%Y-%m-%d %H:%M:%S (%Z)") if last_login else None
    })
    form_user_delete = UserDeleteForm()

  return render(request, "initadmin/moderate_user.html", context={
    "viewed_user": user,
    "form_user_moderate": form_user_moderate,
    "form_user_validate": form_user_validate,
    "form_user_addgroup": form_user_addgroup,
    "form_user_activate": form_user_activate,
    "form_user_delete": form_user_delete
  })

# ===========================  Profile Edit ====================================
@login_required
def profile_edit(request):
  user = request.user
  is_confirmed = user.config.is_scope_confirmed

  # initialise all forms
  form_user_profile = form_user_password = form_user_localisation = form_user_language = form_user_delete = None

  if request.method == "POST":

    # -------------------------- Name Edit -------------------------------------
    if request.POST.get("action", None) == "edit_profile":
      form_user_profile = UserEditForm(request.POST, instance=user)
      new_username = request.POST.get("username")

      if user.username != new_username:
        existing_user_list = User.objects.filter(username=new_username)
        if len(existing_user_list) > 0:
          messages.warning(request, _("This username is already taken. Please choose a different username."))
      else:
        form_user_profile.save()
        messages.success(request, _("Data was updated."))

    # ---------------------------- Scope Edit ----------------------------------
    elif request.POST.get("action", None) == "edit_scope":
      form_user_localisation = UserLocaliseForm(request.POST)
      if is_confirmed != True:
        messages.warning(request, _("Localisation is not possible while previous change has not been validated."))
      else:
        if form_user_localisation.is_valid():

          # create a searchable id to remove all notifications when one moderator answers
          permission = "user_can_localise"
          flag = "".join([permission, ":", str(uuid.uuid4())])
          notify(_get_recipient_list(permission), settings.NOTIFICATIONS.MODERATE.USER_LOCALISATION_REQUESTED, {
            "target": user,
            "description": "".join([
              _("Request to change location. Current location: "),
              user.config.scope,
              ". ",
              _("New location: "),
              request.POST.get("scope")
            ]),
            "flag": flag,
          }, sender=user)

          # save the config
          user.config.is_flagged = user.config.is_flagged + flag + ";"
          form_user_localisation = UserLocaliseForm(request.POST, instance=user.config)
          form_user_localisation.save()
          messages.success(request, _("Localisation request sent. Please wait for validation by the moderation team."))

    # -------------------------- Language Edit ---------------------------------   
    elif request.POST.get("action", None) == "edit_language":
      form_user_language = UserLanguageForm(request.POST, instance=user.config)
      if form_user_language.is_valid():
        form_user_language.save()

      # set active language if it's different from current language
      preferred_language = request.POST.get("language_preference")
      if translation.get_language() != preferred_language:
        translation.activate(preferred_language)
        if hasattr(request, 'session'):
          request.session[translation.LANGUAGE_SESSION_KEY] = preferred_language
      messages.success(request, _("Language preference stored."))

    # -------------------------- Pasword Edit ----------------------------------
    elif request.POST.get("action", None) == "edit_password":
      form_user_password = CustomPasswordChangeForm(request.user, data=request.POST)
      if form_user_password.is_valid():
        form_user_password.save()
        update_session_auth_hash(request, form_user_password.user)
        messages.success(request, _("Password was successfully changed."))
      else:
        messages.warning(request, _("Could not save password. Please correct the errors shown below."))

    # -------------------------- Delete Account --------------------------------
    elif request.POST.get("action", None) == "delete_account":

      # XXX can't do form.is_valid() because I don't want to save the username
      permission = "user_can_delete"
      flag = "".join([permission, ":", str(uuid.uuid4())])
      notify(_get_recipient_list(permission), settings.NOTIFICATIONS.MODERATE.USER_DELETION_REQUESTED, {
        "target": user,
        "description": _("Request to delete account."),
        "flag": flag,
      }, sender=user)

      # save the config
      user.config.is_flagged = user.config.is_flagged + flag + ";"
      form_user_delete=UserDeleteAccount(request.POST, instance=user.config)
      form_user_delete.save()
      user.is_active = False
      user.save()
      messages.success(request, _("Account deletion request sent. Your account will be removed shortly."))

  # GET and inval POSTs pass through here preserving validation errors
  if form_user_profile is None:
    form_user_profile = UserEditForm(instance=user)
  if form_user_delete is None:
    form_user_delete = UserDeleteAccount()
  if form_user_password is None:
    form_user_password = CustomPasswordChangeForm(user=user)
  if form_user_localisation is None:
    form_user_localisation = UserLocaliseForm(initial={
      "scope": user.config.scope,
      "is_scope_confirmed": user.config.is_scope_confirmed
    })
    if is_confirmed != True:
      form_user_localisation.fields['scope'].disabled = True
  if form_user_language is None:
    form_user_language = UserLanguageForm(initial={
      "language_preference": user.config.language_preference or settings.DEFAULT_LANGUAGE
    })

  return render(request, "account/profile_edit.html", context=dict({
    "viewed_user": user,
    "form_user_profile": form_user_profile,
    "form_user_password": form_user_password,
    "form_user_localisation": form_user_localisation,
    "form_user_language": form_user_language,
    "form_user_delete": form_user_delete
  }))

#
#      ___       ______ .___________. __    ______   .__   __.      _______.
#     /   \     /      ||           ||  |  /  __  \  |  \ |  |     /       |
#    /  ^  \   |  ,----'`---|  |----`|  | |  |  |  | |   \|  |    |   (----`
#   /  /_\  \  |  |         |  |     |  | |  |  |  | |  . `  |     \   \    
#  /  _____  \ |  `----.    |  |     |  | |  `--'  | |  |\   | .----)   |   
# /__/     \__\ \______|    |__|     |__|  \______/  |__| \__| |_______/    
#
#
# 
# -------------------------- Delete Invitations --------------------------------
# XXX if we cannot delete, it will be impossible to re-invite someone. The whole 
# batch/signup code handling isn't very flexible.
@login_required
@group_required(settings.PLATFORM_GROUP_VALUE_TITLE_LIST, raise_exception=True)
def delete_csv(request, batch_id):
  if request.user.has_perm("auth.user_can_invite"):
    batch = get_object_or_404(InviteBatch, pk=batch_id)
    if batch:
      err_count = 0
      total_count = 0
      for invite in batch.payload.splitlines()[1:]:
        total_count += 1
        try:
          SignupCode.objects.get(email=invite.split(";")[2]).delete()
        except SignupCode.DoesNotExist:
          err_count += 1
          pass
  
    batch.delete()
    messages.success(request, "".join([
      "{} ".format(total_count),
      _("Signup Codes removed. Batch file deleted."),
      " ({} ".format(err_count),
      _("Codes could not be found"),
      ")"
    ]))
  
    return redirect("/backoffice/invite/")
  
# ------------------------- Download Invitations -------------------------------
@login_required
@group_required(settings.PLATFORM_GROUP_VALUE_TITLE_LIST, raise_exception=True)
def download_csv(request, batch_id):
  if request.user.has_perm("auth.user_can_invite"):
    batch = get_object_or_404(InviteBatch, pk=batch_id)
    response = HttpResponse(batch.payload, content_type="text/csv")
    response["Content-Disposition"] = "attachment; filename=invited_users.csv"
    return response

