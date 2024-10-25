import discord
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button
import asyncio
import datetime
import pytz
import json

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix='/', intents=intents)
tree = bot.tree

remind_sound = 'remind.mp3'
confirm_sound = 'confirm.mp3'
cancel_sound = 'cancel.mp3'
notification_sound = 'notification.mp3'

voice_channel_id = 1289694911234310155
text_channel_id = 1299347859828903977

active_reminders = {}
user_timezones = {}

# Загрузка сохраненных часовых поясов
def load_timezones():
    try:
        with open('user_timezones.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Сохранение часовых поясов
def save_timezones():
    with open('user_timezones.json', 'w') as f:
        json.dump(user_timezones, f)

@bot.event
async def on_ready():
    global user_timezones
    user_timezones = load_timezones()
    print(f'Вход выполнен как {bot.user}')
    await connect_to_voice_channel()
    try:
        synced = await tree.sync()
        print(f"Синхронизировано {len(synced)} команд")
    except Exception as e:
        print(f"Ошибка при синхронизации команд: {e}")
    print("Бот готов к работе")

@bot.event
async def on_voice_state_update(member, before, after):
    if member == bot.user:
        if after.channel is None or after.channel.id != voice_channel_id:
            print("Бот был отключен или перемещен. Попытка переподключения...")
            await attempt_reconnect()

async def attempt_reconnect():
    for attempt in range(5):
        try:
            await connect_to_voice_channel()
            print(f"Успешно переподключился после {attempt + 1} попытки")
            return
        except Exception as e:
            print(f"Попытка {attempt + 1} не удалась: {e}")
            await asyncio.sleep(5)
    print("Не удалось переподключиться после 5 попыток")

async def connect_to_voice_channel():
    voice_channel = bot.get_channel(voice_channel_id)
    if not voice_channel:
        raise ValueError(f"Голосовой канал с ID {voice_channel_id} не найден")

    for vc in bot.voice_clients:
        if vc.guild == voice_channel.guild:
            await vc.disconnect()

    await voice_channel.connect(timeout=60, reconnect=True)
    print(f"Подключен к голосовому каналу: {voice_channel.name}")

@tree.command(name="remind", description="Установить напоминание")
async def remind(interaction: discord.Interaction):
    if not await check_channel_permissions(interaction):
        return

    print("Вызвана команда напоминания")
    if str(interaction.user.id) not in user_timezones:
        await interaction.response.send_modal(TimezoneModal())
    else:
        await interaction.response.send_modal(ReminderModal())

class TimezoneModal(Modal):
    def __init__(self):
        super().__init__(title="Установка часового пояса")
        self.timezone_input = TextInput(label="Часовой пояс", placeholder="Например: Europe/Moscow")
        self.add_item(self.timezone_input)

    async def on_submit(self, interaction: discord.Interaction):
        timezone_value = self.timezone_input.value
        try:
            pytz.timezone(timezone_value)
            user_timezones[str(interaction.user.id)] = timezone_value
            save_timezones()
            await interaction.response.send_message("Часовой пояс успешно установлен.", ephemeral=True)
            await interaction.followup.send_modal(ReminderModal())
        except pytz.exceptions.UnknownTimeZoneError:
            await interaction.response.send_message("Неизвестный часовой пояс. Попробуйте еще раз.", ephemeral=True)

class ReminderModal(Modal):
    def __init__(self):
        super().__init__(title="Установить напоминание")
        self.time_input = TextInput(label="Время (ЧЧ:ММ)", placeholder="Введите время", max_length=5)
        self.message_input = TextInput(label="Сообщение", placeholder="Введите сообщение")
        self.add_item(self.time_input)
        self.add_item(self.message_input)

    async def on_submit(self, interaction: discord.Interaction):
        time_value = self.time_input.value
        message_value = self.message_input.value

        if not validate_time(time_value):
            await interaction.response.send_message("Неверный формат времени! Укажите в формате ЧЧ:ММ.", ephemeral=True)
            return

        await play_sound(interaction, remind_sound)
        view = create_confirmation_view(time_value, message_value)
        await interaction.response.send_message("Подтвердите или отмените напоминание:", view=view)

def validate_time(time_str):
    try:
        hour, minute = map(int, time_str.split(':'))
        return 0 <= hour < 24 and 0 <= minute < 60
    except ValueError:
        return False

def create_confirmation_view(time_value, message_value):
    view = View(timeout=None)
    confirm_button = Button(label="Подтвердить", style=discord.ButtonStyle.green)
    cancel_button = Button(label="Отменить", style=discord.ButtonStyle.red)

    async def confirm_callback(interaction):
        await interaction.response.defer(ephemeral=True)
        print("Нажата кнопка подтверждения")
        await stop_current_sound(interaction)
        await play_sound(interaction, confirm_sound)
        await interaction.message.delete()
        reminder_id = await schedule_reminder(interaction, time_value, message_value)
        active_reminders[reminder_id] = (time_value, message_value)

    async def cancel_callback(interaction):
        await interaction.response.defer(ephemeral=True)
        print("Нажата кнопка отмены")
        await stop_current_sound(interaction)
        await play_sound(interaction, cancel_sound)
        await interaction.message.delete()

    confirm_button.callback = confirm_callback
    cancel_button.callback = cancel_callback
    view.add_item(confirm_button)
    view.add_item(cancel_button)
    return view

async def check_channel_permissions(interaction):
    text_channel = bot.get_channel(text_channel_id)
    voice_channel = bot.get_channel(voice_channel_id)

    if interaction.channel.id != text_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в канале {text_channel.name}.", ephemeral=True)
        return False

    if not interaction.user.voice or interaction.user.voice.channel.id != voice_channel_id:
        await interaction.response.send_message(f"Эту команду можно использовать только в голосовом канале {voice_channel.name}.", ephemeral=True)
        return False

    return True

async def play_sound(interaction, sound_file):
    try:
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_connected():
            if voice_client.is_playing():
                voice_client.stop()
            voice_client.play(discord.FFmpegPCMAudio(sound_file))
            print(f"Воспроизведение {sound_file} завершено успешно.")
        else:
            print("Голосовой клиент не подключен или недоступен.")
    except Exception as e:
        print(f"Ошибка при воспроизведении звука: {e}")

async def stop_current_sound(interaction):
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()

async def schedule_reminder(interaction, time_value, message_value):
    user_tz = pytz.timezone(user_timezones.get(str(interaction.user.id), 'UTC'))
    now = datetime.datetime.now(user_tz)
    reminder_time = user_tz.localize(datetime.datetime.strptime(f"{now.date()} {time_value}", "%Y-%m-%d %H:%M"))

    if reminder_time < now:
        reminder_time += datetime.timedelta(days=1)

    delay = (reminder_time - now).total_seconds()
    reminder_id = len(active_reminders) + 1

    asyncio.create_task(send_reminder(interaction, delay, message_value, reminder_id))
    return reminder_id

async def send_reminder(interaction, delay, message, reminder_id):
    try:
        await asyncio.sleep(delay)
        if reminder_id in active_reminders:
            channel = bot.get_channel(text_channel_id)
            if channel:
                await channel.send(f"Напоминание: {message}")
                print(f"Отправлено напоминание: {message}")
                try:
                    await play_sound(interaction, notification_sound)
                except Exception as e:
                    print(f"Ошибка при воспроизведении звука уведомления: {e}")
            else:
                print(f"Не удалось найти канал с ID {text_channel_id}")
            del active_reminders[reminder_id]
        else:
            print(f"Напоминание с ID {reminder_id} было отменено")
    except Exception as e:
        print(f"Ошибка при отправке напоминания: {e}")

@tree.command(name="all", description="Показать все активные напоминания")
async def show_all_reminders(interaction: discord.Interaction):
    if not await check_channel_permissions(interaction):
        return

    if not active_reminders:
        await interaction.response.send_message("Нет активных напоминаний.", ephemeral=True)
        return

    embed = discord.Embed(title="Активные напоминания", color=discord.Color.blue())
    for reminder_id, (time, message) in active_reminders.items():
        embed.add_field(name=f"ID: {reminder_id}", value=f"Время: {time}\nСообщение: {message}", inline=False)

    view = create_all_reminders_view()
    await interaction.response.send_message(embed=embed, view=view)

def create_all_reminders_view():
    view = View(timeout=None)
    for reminder_id in active_reminders.keys():
        button = Button(label=f"Отменить {reminder_id}", style=discord.ButtonStyle.red, custom_id=str(reminder_id))
        button.callback = create_cancel_callback(reminder_id)
        view.add_item(button)

    exit_button = Button(label="Выход", style=discord.ButtonStyle.grey, custom_id="exit")
    exit_button.callback = exit_callback
    view.add_item(exit_button)

    return view

async def exit_callback(interaction: discord.Interaction):
    await interaction.message.delete()
    await interaction.response.send_message("Вы вышли из меню активных напоминаний.", ephemeral=True)

def create_cancel_callback(reminder_id):
    async def cancel_callback(interaction: discord.Interaction):
        await interaction.response.defer()
        if reminder_id in active_reminders:
            del active_reminders[reminder_id]
            await stop_current_sound(interaction)
            await play_sound(interaction, cancel_sound)

            if not active_reminders:
                await interaction.message.delete()
                await interaction.followup.send("Все напоминания отменены. Меню закрыто.", ephemeral=True)
            else:
                embed = discord.Embed(title="Активные напоминания", color=discord.Color.blue())
                for r_id, (time, message) in active_reminders.items():
                    embed.add_field(name=f"ID: {r_id}", value=f"Время: {time}\nСообщение: {message}", inline=False)

                view = create_all_reminders_view()
                await interaction.message.edit(embed=embed, view=view)

    return cancel_callback

@tree.command(name="settimezone", description="Установить или изменить ваш часовой пояс")
async def set_timezone(interaction: discord.Interaction):
    await interaction.response.send_modal(TimezoneModal())

bot.run('YOUR_BOT_TOKEN')
